"""The index, and the one property that makes it safe to have: it is DERIVED.

Everything else here — upsert, get, search, the HDT grouping — is ordinary. The
test that carries the architecture is `test_reindex_rebuilds_from_the_containers`:
if the index can be thrown away and rebuilt from the object store, then it was
never a second truth, and a catalogue can change index implementation without
migrating anything.
"""

from __future__ import annotations

import os
import urllib.request

import pytest

from app.index import (CouchDbCatalogIndex, SqliteCatalogIndex, group_by_hdt,
                       index_from_env)
from app.store import InMemoryContainerStore

from s3dgraphy import api as em


@pytest.fixture()
def index():
    return SqliteCatalogIndex(":memory:")


def _card(doc, study_id):
    return em.study_metadata(doc, study_id=study_id)


# ── the ordinary half ────────────────────────────────────────────────────────

def test_upsert_get_and_replace(index, public_study):
    card = _card(public_study, "study:a")
    index.upsert(card)
    assert index.get("study:a")["title"] == "Sarmizegetusa 2026"

    card["title"] = "Sarmizegetusa 2026 (rev)"
    index.upsert(card)
    assert index.get("study:a")["title"] == "Sarmizegetusa 2026 (rev)"
    assert len(index.search()) == 1, "an upsert replaces, it does not accumulate"


def test_a_card_without_an_id_is_refused(index, public_study):
    card = _card(public_study, "study:a")
    card["id"] = None
    with pytest.raises(ValueError, match="id"):
        index.upsert(card)


def test_search_by_text_author_orcid_and_licence(index, public_study,
                                                 restricted_study):
    index.upsert(_card(public_study, "study:a"))
    index.upsert(_card(restricted_study, "study:b"))

    # the free text covers the twin's name too, so both campaigns on the same
    # monument answer to it — which is what somebody typing a place name means
    assert {c["id"] for c in index.search(q="sarmizegetusa")} == {"study:a",
                                                                 "study:b"}
    assert [c["id"] for c in index.search(q="scavo in corso")] == ["study:b"]
    assert [c["id"] for c in index.search(author="tizia")] == ["study:b"]
    assert [c["id"] for c in index.search(orcid="0000-0002-1825-0097")] == ["study:a"]
    assert [c["id"] for c in index.search(license="CC-BY-4.0")] == ["study:a"]
    assert {c["id"] for c in index.search()} == {"study:a", "study:b"}


def test_search_by_twin_groups_the_studies_of_one_object(index, public_study,
                                                         restricted_study,
                                                         other_twin_study):
    index.upsert(_card(public_study, "study:a"))
    index.upsert(_card(restricted_study, "study:b"))
    index.upsert(_card(other_twin_study, "study:c"))

    same_twin = index.search(hc2="https://example.org/h/sarm")
    assert {c["id"] for c in same_twin} == {"study:a", "study:b"}, \
        "two campaigns on the same monument are one HDT"


def test_the_hdt_view_keeps_the_homeless_studies_last(index):
    cards = [
        {"id": "s1", "hc2": {"id": "h1", "iri": "iri:1"}, "hc1": {"id": "e1"}},
        {"id": "s2", "hc2": {"id": "h1", "iri": "iri:1"}, "hc1": None},
        {"id": "s3", "hc2": None, "hc1": None},
    ]
    groups = group_by_hdt(cards)
    assert [g["key"] for g in groups] == ["iri:1", None]
    assert groups[0]["count"] == 2
    assert groups[0]["hc1"] == {"id": "e1"}, \
        "the entity is taken from whichever study names it"
    assert groups[1]["studies"][0]["id"] == "s3", \
        "a study with no twin is kept, not dropped"


def test_removal(index, public_study):
    index.upsert(_card(public_study, "study:a"))
    assert index.remove("study:a") is True
    assert index.remove("study:a") is False
    assert index.get("study:a") is None


# ── the half that carries the architecture ───────────────────────────────────

def test_reindex_rebuilds_from_the_containers(index, public_study,
                                              restricted_study):
    """Throw the index away; rebuild it by re-reading the object store.

    Card for card, byte for byte. If this holds, the index is a projection and
    nothing else in the catalogue has to be careful about keeping it in sync —
    which is the difference between a cache and a second database.
    """
    store = InMemoryContainerStore()
    store.put("study:a", public_study)
    store.put("study:b", restricted_study)
    for study_id in store.list():
        index.upsert(_card(store.get(study_id), study_id))
    before = {c["id"]: c for c in index.search()}

    # the index is now corrupted / lost / replaced by another implementation
    index.remove("study:a")
    index.upsert({"id": "study:ghost", "title": "never existed",
                  "visibility": "public"})
    assert {c["id"] for c in index.search()} != set(before)

    rebuilt = index.reindex(_card(store.get(sid), sid) for sid in store.list())
    assert rebuilt == 2
    after = {c["id"]: c for c in index.search()}
    assert after == before, "the containers ARE the truth"
    assert index.get("study:ghost") is None, \
        "a rebuild removes what the object store does not have"


def test_a_failed_rebuild_leaves_the_index_alone(index, public_study):
    """All or nothing. A rebuild that half-succeeded would silently lose studies
    — the exact failure a rebuild exists to repair."""
    index.upsert(_card(public_study, "study:a"))
    before = index.search()

    def cards_then_explode():
        yield _card(public_study, "study:a")
        raise RuntimeError("the object store went away mid-rebuild")

    with pytest.raises(RuntimeError):
        index.reindex(cards_then_explode())
    assert index.search() == before


# ── choosing an implementation ───────────────────────────────────────────────

def test_sqlite_is_the_dev_default_and_couchdb_is_never_silent():
    assert isinstance(index_from_env({}), SqliteCatalogIndex)
    assert isinstance(index_from_env({"EM_CATALOG_DB": ":memory:"}),
                      SqliteCatalogIndex)


def test_a_half_configured_couchdb_refuses_to_start():
    """The same refusal the object store makes, for the same reason: an operator
    who believes their records are in CouchDB must not find them in a file."""
    with pytest.raises(RuntimeError, match="half-configured"):
        index_from_env({"COUCHDB_URL": "http://couch:5984",
                        "COUCHDB_USER": "admin"})


def test_the_couchdb_implementation_says_so_when_it_cannot_be_reached():
    """It is a deploy-time class and it is exercised HERE only to the point the
    dev machine allows: constructing it against nothing must fail with a
    sentence, not with a stack trace at somebody's first search.

    Measured against a CouchDB when one is up (the dev-stack profile); this
    assertion is the part that holds without one, and the limit is declared.
    """
    with pytest.raises(RuntimeError, match="did not answer"):
        CouchDbCatalogIndex("http://127.0.0.1:1", database="nope", timeout=1)


def test_the_named_entity_wins_over_the_iri_only_stub():
    """`study_metadata` invents an HC1 from the twin's IRI when a study never
    authored a HeritageEntityNode. That stub must not outrank the study that
    actually names the monument — found by the live smoke, where the group came
    back nameless while the name sat in the very next card."""
    stub = {"id": None, "name": None, "kind": None, "iri": "iri:1"}
    named = {"id": "e1", "name": "Sarmizegetusa Regia", "kind": "site"}
    cards = [
        {"id": "s1978", "hc2": {"id": "h1", "iri": "iri:1"}, "hc1": stub},
        {"id": "s2026", "hc2": {"id": "h1", "iri": "iri:1"}, "hc1": named},
    ]
    assert group_by_hdt(cards)[0]["hc1"] == named
    # …and the order must not decide it
    assert group_by_hdt(list(reversed(cards)))[0]["hc1"] == named


# ── the DEPLOY index, against a real CouchDB when there is one ───────────────

COUCH_URL = os.environ.get("EM_CATALOG_TEST_COUCHDB", "http://localhost:5985")


def _couch_is_up() -> bool:
    try:
        with urllib.request.urlopen(f"{COUCH_URL}/_up", timeout=2) as answer:
            return answer.status == 200
    except Exception:
        return False


@pytest.mark.skipif(not _couch_is_up(),
                    reason=f"no CouchDB at {COUCH_URL} — start the dev-stack "
                           f"`couchdb` profile to measure the deploy index")
def test_the_couchdb_index_answers_exactly_like_the_dev_one(public_study,
                                                            restricted_study,
                                                            other_twin_study):
    """The interface is the contract, so the two implementations must agree.

    Not "CouchDB works" — that is Apache's problem. What is measured is that a
    catalogue swapping its index gets the SAME answers, which is what makes the
    swap a line of configuration rather than a migration.
    """
    import base64

    database = "StratiGraph Catalog-test"
    couch = index_from_env({"COUCHDB_URL": COUCH_URL, "COUCHDB_USER": "admin",
                            "COUCHDB_PASSWORD": "admin",
                            "COUCHDB_DATABASE": database})
    assert isinstance(couch, CouchDbCatalogIndex)
    sqlite = SqliteCatalogIndex(":memory:")

    cards = [_card(public_study, "study:a"), _card(restricted_study, "study:b"),
             _card(other_twin_study, "study:c")]
    try:
        for card in cards:
            couch.upsert(card)
            sqlite.upsert(card)

        for query in ({}, {"q": "colosseo"}, {"author": "tizia"},
                      {"hc2": "https://example.org/h/sarm"},
                      {"visibility": "public"}, {"license": "CC-BY-4.0"}):
            assert ([c["id"] for c in couch.search(**query)]
                    == [c["id"] for c in sqlite.search(**query)]), query

        assert couch.get("study:a") == sqlite.get("study:a")
        assert ([(g["key"], g["count"]) for g in couch.list(view="hdt")]
                == [(g["key"], g["count"]) for g in sqlite.list(view="hdt")])

        couch.upsert(cards[0])                       # idempotent
        assert len(couch.search()) == 3
        assert couch.remove("study:c") is True
        assert couch.remove("study:c") is False
        assert couch.reindex(cards) == 3
        assert sorted(c["id"] for c in couch.search()) == ["study:a", "study:b",
                                                           "study:c"]
    finally:
        # the test leaves nothing behind in somebody's CouchDB
        request = urllib.request.Request(f"{COUCH_URL}/{database}",
                                         method="DELETE")
        request.add_header("Authorization", "Basic " + base64.b64encode(
            b"admin:admin").decode())
        try:
            urllib.request.urlopen(request, timeout=5)
        except Exception:
            pass
