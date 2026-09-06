"""The merge, and the four things that make it honest.

E.D.'s decision of 1 October 2026 is **alias only**: no document is touched. So
every test here asks the same question from a different side — *did the register
change without anybody's graph changing?* — and the two that carry the design
are:

* `test_the_alias_survives_a_real_reindex` — the trap. The alias table lives in
  the OBJECT STORE, because `reindex` does `DELETE FROM studies` and rebuilds
  from the containers, and rebuilding is the ordinary way this service repairs
  itself. An alias that lived in the index would quietly stop being true.
* `test_unmerging_restores_the_register_exactly` — the whole argument for
  choosing aliases. Compared as serialised JSON, not by eye.
"""

from __future__ import annotations

import json

import pytest

from app import aliases
from app.index import SqliteCatalogIndex, group_by_hdt, hdt_key

from s3dgraphy import api as em

ALIAS_KEY = aliases.ALIAS_KEY

SARM = "https://example.org/h/sarm"
COLOSSEO = "https://example.org/h/colosseo"


@pytest.fixture()
def registry(monkeypatch):
    """A store and an index nobody else wrote, plus an empty alias table."""
    from app.store import InMemoryContainerStore

    aliases.reset()
    store = InMemoryContainerStore()
    index = SqliteCatalogIndex(":memory:")
    yield store, index
    aliases.reset()


def _put(store, index, doc, study_id):
    store.put(study_id, doc)
    index.upsert(em.study_metadata(doc, study_id=study_id))


def _rebuild(store, index):
    """A REAL reindex: drop the rows, re-read the bucket, rebuild the cards."""
    cards = [em.study_metadata(store.get(sid), study_id=sid)
             for sid in store.list()]
    return index.reindex(cards)


def _groups(index):
    return {g["key"]: sorted(s["id"] for s in g["studies"])
            for g in group_by_hdt(index.search())}


# ── 1 · the trap ─────────────────────────────────────────────────────────────

def test_the_alias_survives_a_real_reindex(registry, public_study,
                                           other_twin_study):
    store, index = registry
    _put(store, index, public_study, "study:sarm")
    _put(store, index, other_twin_study, "study:colosseo")
    assert len(_groups(index)) == 2, "two twins to begin with"

    aliases.merge(store, COLOSSEO, SARM, author="0000-0002-1825-0097")
    assert len(_groups(index)) == 1

    # The bucket is the truth: throw the index away entirely and rebuild.
    index2 = SqliteCatalogIndex(":memory:")
    aliases.reset()                       # …and forget the in-memory table too
    aliases.load(store)                   # a fresh process reading the store
    _rebuild(store, index2)

    assert aliases.canonical_key(COLOSSEO) == SARM, \
        "the alias came back from the object store, not from the index"
    assert len(_groups(index2)) == 1
    assert _groups(index2) == {SARM: ["study:colosseo", "study:sarm"]}


def test_the_stored_column_carries_the_canonical_key(registry, public_study,
                                                     other_twin_study):
    """The gate for «the alias is applied in ONE place».

    `group_by_hdt` canonicalises off the CARD, so the grouping looks right even
    when the stored column is stale — which is precisely how two derivation
    points hide from each other. What gives it away is a SEARCH: the column is
    what `search(hc2=…)` filters on, so if `_hdt_keys` derived the key its own
    way, the surviving key would find only its own studies after a rebuild.
    """
    store, index = registry
    _put(store, index, public_study, "study:sarm")
    _put(store, index, other_twin_study, "study:colosseo")
    aliases.merge(store, COLOSSEO, SARM, author="dev")
    _rebuild(store, index)

    assert {c["id"] for c in index.search(hc2=SARM)} == \
        {"study:sarm", "study:colosseo"}, \
        "the surviving key finds both studies — the column was written canonical"
    assert index.search(hc2=COLOSSEO) == [], \
        "…and nothing is still filed under the key that lost"


def test_the_alias_is_not_in_the_index_and_not_listed_as_a_study(registry,
                                                                 public_study):
    store, index = registry
    _put(store, index, public_study, "study:sarm")
    aliases.merge(store, COLOSSEO, SARM, author="dev")

    assert store.get_blob(ALIAS_KEY), "the table is an object in the store"
    assert "registry/twin-aliases" not in " ".join(store.list()), \
        "…and store.list() must not offer it to reindex as a study"
    assert store.list() == ["study:sarm"]


# ── 2 · the whole round trip ─────────────────────────────────────────────────

def test_unmerging_restores_the_register_exactly(registry, public_study,
                                                 other_twin_study):
    store, index = registry
    _put(store, index, public_study, "study:sarm")
    _put(store, index, other_twin_study, "study:colosseo")

    before = json.dumps(_groups(index), sort_keys=True)
    assert len(json.loads(before)) == 2

    aliases.merge(store, COLOSSEO, SARM, author="dev")
    _rebuild(store, index)
    merged = _groups(index)
    assert merged == {SARM: ["study:colosseo", "study:sarm"]}, \
        "one twin, with the studies of both"

    aliases.unmerge(store, COLOSSEO)
    _rebuild(store, index)
    after = json.dumps(_groups(index), sort_keys=True)

    assert after == before, "the register is what it was, compared as bytes"


def test_a_chain_resolves_to_the_surviving_twin(registry):
    store, _index = registry
    aliases.merge(store, "c", "b", author="dev")
    aliases.merge(store, "b", "a", author="dev")
    assert aliases.canonical_key("c") == "a", "a→b→c collapses to the survivor"
    assert aliases.merged_from("a") == ["b", "c"]


def test_a_cycle_is_refused_rather_than_hung_on(registry):
    store, _index = registry
    aliases.merge(store, "b", "a", author="dev")
    with pytest.raises(aliases.AliasError):
        aliases.merge(store, "a", "b", author="dev")


# ── 3 · the author ───────────────────────────────────────────────────────────

def test_a_merge_records_who_decided(registry):
    store, _index = registry
    out = aliases.merge(store, COLOSSEO, SARM, author="0000-0002-1825-0097")
    assert out["by"] == "0000-0002-1825-0097" and out["at"]
    assert aliases.entry(COLOSSEO)["by"] == "0000-0002-1825-0097"


def test_a_merge_without_an_author_is_refused(registry):
    store, _index = registry
    with pytest.raises(aliases.AliasError):
        aliases.merge(store, COLOSSEO, SARM, author="")


def test_the_endpoint_refuses_an_unauthenticated_merge(client, realm):
    answer = client.post("/catalog/twins/merge",
                         json={"loser": COLOSSEO, "winner": SARM})
    assert answer.status_code == 401, answer.text


def test_the_endpoint_merges_and_unmerges_with_a_token(client, realm,
                                                       public_study,
                                                       other_twin_study):
    head = {"Authorization": f"Bearer {realm()}"}
    for doc, sid in ((public_study, "study:sarm"),
                     (other_twin_study, "study:colosseo")):
        assert client.post("/catalog/studies", json=doc,
                           params={"study_id": sid},
                           headers=head).status_code in (200, 201)

    merged = client.post("/catalog/twins/merge",
                         json={"loser": COLOSSEO, "winner": SARM}, headers=head)
    assert merged.status_code == 200, merged.text
    assert merged.json()["merged_into"] == SARM
    assert merged.json()["by"], "the decider is on the record"

    listed = client.get("/catalog/twins/aliases").json()
    assert listed["count"] == 1 and COLOSSEO in listed["aliases"]

    undone = client.post("/catalog/twins/unmerge", json={"loser": COLOSSEO},
                         headers=head)
    assert undone.status_code == 200, undone.text
    assert client.get("/catalog/twins/aliases").json()["count"] == 0


def test_a_dev_mode_merge_says_it_was_unsigned(client):
    """Dev mode has no OIDC, so every write is unauthenticated — including this
    one. The register must not record that as if somebody had signed it."""
    answer = client.post("/catalog/twins/merge",
                         json={"loser": COLOSSEO, "winner": SARM})
    assert answer.status_code == 200, answer.text
    assert answer.json()["by"] == "anonymous@dev-no-auth", \
        "an author nobody can trace has to be legible AS one"


# ── 4 · the losing key still answers, and says what happened ─────────────────

def test_the_losing_key_answers_with_merged_into(client, realm, public_study,
                                                 other_twin_study):
    head = {"Authorization": f"Bearer {realm()}"}
    for doc, sid in ((public_study, "study:sarm"),
                     (other_twin_study, "study:colosseo")):
        client.post("/catalog/studies", json=doc, params={"study_id": sid},
                    headers=head)
    client.post("/catalog/twins/merge",
                json={"loser": COLOSSEO, "winner": SARM}, headers=head)
    client.post("/catalog/reindex", headers=head)

    answer = client.get(f"/catalog/hdt/{COLOSSEO}")
    assert answer.status_code == 200, "not a 404: a merged twin still exists"
    body = answer.json()
    assert body["merged_into"] == SARM
    assert body["asked"] == COLOSSEO
    assert body["merged_by"], "…and who decided it"
    assert body["hc2"] == SARM, "…and the body is the surviving group"
    assert {s["id"] for s in body["studies"]} == {"study:sarm", "study:colosseo"}

    winner = client.get(f"/catalog/hdt/{SARM}").json()
    assert winner["merged_from"] == [COLOSSEO], "the winner names what it absorbed"
    assert "merged_into" not in winner, "…and is not itself merged into anything"


# ── 5 · whoever was disconnected ─────────────────────────────────────────────

def test_somebody_disconnected_keeps_working_on_the_losing_key(registry,
                                                               other_twin_study):
    """Their document is not touched — measured on the bytes, not asserted."""
    store, index = registry
    _put(store, index, other_twin_study, "study:colosseo")
    before = store.get_blob("studies/study_colosseo.em.json")

    aliases.merge(store, COLOSSEO, SARM, author="dev")
    _rebuild(store, index)

    after = store.get_blob("studies/study_colosseo.em.json")
    assert after == before, "the merge did not write a byte into their container"

    # …and their own twin still names the key they know
    card = em.study_metadata(store.get("study:colosseo"), study_id="study:colosseo")
    assert card["hc2"]["iri"] == COLOSSEO, \
        "the document still says what it always said"
    # only the REGISTER groups it elsewhere
    assert hdt_key(card["hc2"]) == SARM


# ── 6 · the state arrives instead of being inferred ─────────────────────────

def test_the_twin_state_reaches_the_register_as_a_record(registry):
    """s3Dgraphy's two lines: `hdt_status` on the card, not derived from the
    absence of a key."""
    from s3dgraphy.container import build_container, container_of
    from s3dgraphy.graph import Graph
    from s3dgraphy.nodes.hdt_node import HDTNode

    graph = Graph(graph_id="stato")
    node = HDTNode("hdt_x", name="X", heritage_entity_iri=SARM)
    node.data["hdt_status"] = "registered"
    node.data["hdt_merged_from"] = COLOSSEO
    graph.add_node(node)
    doc = build_container(container_of(graph))

    card = em.study_metadata(doc, study_id="study:stato")
    assert card["hc2"]["hdt_status"] == "registered", \
        "the state is CARRIED, not deduced from the presence of an iri"
    assert card["hc2"]["hdt_merged_from"] == COLOSSEO
