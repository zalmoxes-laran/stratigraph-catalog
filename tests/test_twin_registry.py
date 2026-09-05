"""The twin register — «which twins do I know», and everything it must not do.

The catalogue could always answer «which studies does this twin have». It could
not answer the question somebody standing in a trench actually asks: *is there
already a twin for this, or am I the first?* Without that answer a fourth
campaign mints a fourth twin for one monument, and nobody finds out until a
publication.

What is defended here, and each of these is a way the register could be worse
than not having one:

* it **suggests and never gates** — the studies with no twin are counted and
  named (`untwinned`), because not knowing yet is a state and not a defect;
* every result carries the **three facts that make attaching safe**: which
  register answered, who is already working on it, and how many studies hang
  on it. Attaching to the wrong twin is worse than minting a new one;
* a **provisional** twin — one known only by the id its own document minted —
  says so. Somebody else's provisional is precisely the twin you must not
  attach yourself to;
* the answer is **federated in shape with one source built**, and the source
  that does not exist says «not configured» rather than returning nothing in
  silence — «nobody has a twin for this» and «I only asked one of two places»
  are different sentences;
* the **visibility rule is the same one** `/studies` applies. A register that
  leaked the existence of an unpublished twin would be worse than no register.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from conftest import study_document                       # noqa: E402

from app.twins import (DeclaredSource, STATUS_NOT_CONFIGURED,  # noqa: E402
                       STATUS_OK, custodians_of, is_provisional,
                       search_twins, twins_of, untwinned_count)


def _register(client, doc, realm=None):
    headers = {"Authorization": f"Bearer {realm()}"} if realm else {}
    answer = client.post("/catalog/studies", json=doc, headers=headers)
    assert answer.status_code == 201, answer.text
    return answer.json()


def _twin(client, **params):
    answer = client.get("/catalog/twins", params=params)
    assert answer.status_code == 200, answer.text
    return answer.json()


# ── the register answers, with the three facts ───────────────────────────────

def test_the_register_names_the_twins_it_knows(client):
    """Two campaigns on one monument are ONE twin with two studies — which is
    the whole point of asking before minting a third."""
    _register(client, study_document(graph_id="sarm-2013", title="Sarmizegetusa 2013",
                                     author="Emanuel Demetrescu"))
    _register(client, study_document(graph_id="sarm-2026", title="Sarmizegetusa 2026",
                                     author="Tizia Caia", orcid=None))
    body = _twin(client)

    keys = [t["key"] for t in body["twins"]]
    assert keys == ["https://example.org/h/sarm"], body
    twin = body["twins"][0]
    assert twin["studies"] == 2
    assert twin["source"] == "catalog"
    assert {c["name"] for c in twin["custodians"]} == {"Emanuel Demetrescu",
                                                       "Tizia Caia"}
    # the derivation is NAMED: nothing in a card records a custodian, and a
    # derivation presented as a record is a lie that reads as data
    assert twin["custodians_from"] == "study-authors"


def test_search_finds_by_name_and_by_identity(client):
    _register(client, study_document())
    _register(client, study_document(
        graph_id="colosseo-2024", title="Colosseo 2024", author="Sempronio",
        orcid=None, hdt=("hdt_col", "Colosseo HDT",
                         "https://example.org/h/colosseo"),
        entity=("hc1_col", "Colosseo")))

    assert [t["label"] for t in _twin(client, q="colosseo")["twins"]] \
        == ["Colosseo HDT"]
    # …and by the identity, which is what a tool holding an authority URI has
    assert [t["label"] for t in
            _twin(client, q="https://example.org/h/sarm")["twins"]] \
        == ["Sarmizegetusa HDT"]


def test_a_search_that_finds_nothing_says_so_without_inventing(client):
    _register(client, study_document())
    body = _twin(client, q="stonehenge")
    assert body["twins"] == []
    assert body["count"] == 0
    # and it still says WHO was asked — «nobody has one» is only meaningful
    # next to the list of registers that answered
    assert [s["id"] for s in body["sources"]] == ["catalog", "cloud"]


# ── the state that is not an error ───────────────────────────────────────────

def test_studies_with_no_twin_are_counted_and_not_hidden(client):
    """The homeless bucket is a citizen. A register reporting zero missing
    links while three excavations have no twin would be lying about the
    ordinary case."""
    _register(client, study_document())
    _register(client, study_document(graph_id="scavo-1", title="Trincea 1",
                                     hdt=None, entity=None))
    _register(client, study_document(graph_id="scavo-2", title="Trincea 2",
                                     hdt=None, entity=None))
    body = _twin(client)
    assert body["untwinned"] == 2
    assert body["count"] == 1              # …and they are not twins


def test_a_provisional_twin_says_it_is_provisional(client):
    """A twin with no IRI is known only by the id its own document minted.
    Legitimate, ordinary — and NOT a good place for somebody else to attach."""
    _register(client, study_document(
        graph_id="trincea-2026", title="Trincea 2026",
        hdt=("hdt_local_1", "Nuovo gemello", None), entity=("hc1_x", "Qualcosa")))
    body = _twin(client)
    twin = body["twins"][0]
    assert twin["key"] == "hdt_local_1"     # the node id, not an IRI
    assert twin["provisional"] is True

    # …and a registered one does not claim to be provisional
    _register(client, study_document())
    registered = [t for t in _twin(client)["twins"]
                  if t["key"] == "https://example.org/h/sarm"][0]
    assert registered["provisional"] is False


# ── the shape that lets a second register arrive ─────────────────────────────

def test_the_cloud_is_declared_absent_and_never_simulated(client):
    _register(client, study_document())
    body = _twin(client)
    by_id = {s["id"]: s for s in body["sources"]}

    assert by_id["catalog"]["status"] == STATUS_OK
    assert by_id["catalog"]["count"] == 1
    cloud = by_id["cloud"]
    assert cloud["status"] == STATUS_NOT_CONFIGURED
    assert cloud["count"] == 0
    assert "not part of this deployment" in cloud["detail"]
    # every result names where it came from — the property a second register
    # cannot be added without
    assert all(t["source"] in by_id for t in body["twins"])


def test_a_declared_source_returns_nothing_ever():
    """The guard fired on a case that would break it: a DeclaredSource asked a
    question it could answer plausibly still answers with silence."""
    absent = DeclaredSource("cloud", "collaborative-cloud", "Cloud", "not here")
    assert absent.search(query="sarmizegetusa") == []
    assert absent.describe()["status"] == STATUS_NOT_CONFIGURED


def test_a_second_source_joins_without_changing_the_shape():
    """Three lines tomorrow: a class with `describe`/`search`, and one entry in
    the list. Measured here so the claim in the module docstring is not a hope.
    """
    class FakeRemote:
        id, kind, label = "partner", "catalog", "A partner catalogue"

        def describe(self):
            return {"id": self.id, "kind": self.kind, "label": self.label,
                    "status": STATUS_OK}

        def search(self, query="", limit=20):
            return [{"key": "https://partner.example/h/1", "label": "Theirs",
                     "source": self.id, "studies": 7, "custodians": [],
                     "custodians_from": "study-authors", "provisional": False,
                     "hc1": None, "hc2": None}]

    cards = [study_card("mine", "https://example.org/h/sarm", "Mine")]

    class Local:
        id, kind, label = "catalog", "catalog", "this catalogue"

        def describe(self):
            return {"id": self.id, "kind": self.kind, "label": self.label,
                    "status": STATUS_OK}

        def search(self, query="", limit=20):
            return twins_of(cards, query=query, limit=limit, source=self.id)

    body = search_twins([Local(), FakeRemote()])
    assert [s["id"] for s in body["sources"]] == ["catalog", "partner"]
    # the partner's twin comes first: 7 studies beat 1, and the ORDER is by the
    # fact a person chooses on, not by which register happened to answer first
    assert [t["source"] for t in body["twins"]] == ["partner", "catalog"]


def study_card(study_id, hc2_iri, title, authors=("Rossi",)):
    """A card, hand-built — the unit tests below work on cards, not on HTTP."""
    return {"id": study_id, "title": title,
            "authors": [{"name": a, "orcid": None} for a in authors],
            "hc2": {"id": f"n_{study_id}", "name": f"{title} HDT",
                    "iri": hc2_iri},
            "hc1": {"id": f"e_{study_id}", "name": title, "kind": "site"},
            "visibility": "public"}


# ── the visibility rule is the one the catalogue already has ─────────────────

def test_an_anonymous_caller_sees_only_the_public_twins(client, realm):
    _register(client, study_document(), realm)
    _register(client, study_document(
        graph_id="scavo-in-corso", title="Scavo in corso", visibility="restricted",
        hdt=("hdt_segreto", "Gemello non pubblicato",
             "https://example.org/h/segreto"), entity=None), realm)

    anonymous = _twin(client)
    assert [t["key"] for t in anonymous["twins"]] == ["https://example.org/h/sarm"]

    answer = client.get("/catalog/twins",
                        headers={"Authorization": f"Bearer {realm()}"})
    assert answer.status_code == 200
    assert sorted(t["key"] for t in answer.json()["twins"]) == [
        "https://example.org/h/sarm", "https://example.org/h/segreto"]


# ── the pieces, on their own ─────────────────────────────────────────────────

def test_two_authors_without_an_orcid_are_two_people():
    """MEASURED ON A LIVE CATALOGUE, 30 September 2026: s3Dgraphy writes the
    sentinel `noorcid` when nobody gave one, and it arrived in the card as the
    author's ORCID. Deduplicating on it would have folded every unidentified
    excavator on a monument into ONE custodian — a register answering «who holds
    this» with a name that is not a person's."""
    people = custodians_of([
        {"authors": [{"name": "Tizia Caia", "orcid": "noorcid"}]},
        {"authors": [{"name": "Sempronio", "orcid": "noorcid"}]},
    ])
    assert [p["name"] for p in people] == ["Tizia Caia", "Sempronio"]
    # …and the sentinel is not repeated back as if it were an identity
    assert all("orcid" not in p for p in people)


def test_custodians_are_deduplicated_on_the_orcid():
    cards = [
        {"authors": [{"name": "E. Demetrescu", "orcid": "0000-0002-1825-0097"}]},
        {"authors": [{"name": "Emanuel Demetrescu",
                      "orcid": "0000-0002-1825-0097"},
                     {"name": "Tizia Caia", "orcid": None}]},
    ]
    people = custodians_of(cards)
    assert [p["name"] for p in people] == ["E. Demetrescu", "Tizia Caia"]


def test_is_provisional_reads_the_identity_and_not_the_name():
    assert is_provisional(None) is True
    assert is_provisional({"id": "n1", "name": "Twin", "iri": None}) is True
    assert is_provisional({"id": "n1", "name": "Twin", "iri": "  "}) is True
    assert is_provisional({"id": "n1", "iri": "https://x/1"}) is False


def test_untwinned_counts_studies_not_groups():
    cards = [study_card("a", "https://x/1", "A"),
             {"id": "b", "title": "B", "authors": [], "hc2": None, "hc1": None},
             {"id": "c", "title": "C", "authors": [], "hc2": None, "hc1": None}]
    assert untwinned_count(cards) == 2
    assert len(twins_of(cards)) == 1
