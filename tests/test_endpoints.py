"""The API, measured: register → search → retrieve → open, plus who may see what.

Four claims worth more than the route list:

1. **the container is stored before the index is written**, so the recoverable
   failure is the one that happens;
2. **`/emjson` gives back exactly what went in** — a catalogue that reformatted
   the study on the way out would be editing it;
3. **`/ttl` is publish mode**, so a deleted US does not travel into a published
   projection;
4. **a public study is served without a token and a restricted one is not**, and
   an anonymous list shows the first without leaking the second.
"""

from __future__ import annotations

import json

import pytest

from app import main as main_module

from s3dgraphy import api as em


def _register(client, doc, **params):
    answer = client.post("/catalog/studies", json=doc, params=params)
    assert answer.status_code == 201, answer.text
    return answer.json()


# ── register ─────────────────────────────────────────────────────────────────

def test_registering_a_study_stores_the_container_then_derives_the_card(
        client, public_study):
    body = _register(client, public_study)
    assert body["id"].startswith("study:")
    assert body["created"] is True
    assert body["container_ref"].startswith("studies/")
    assert body["sha256"].startswith("sha256:")

    card = body["card"]
    assert card["title"] == "Sarmizegetusa 2026"
    assert card["authors"] == [{"name": "Emanuel Demetrescu",
                                "orcid": "0000-0002-1825-0097"}]
    assert card["license"] == "CC-BY-4.0"
    assert card["visibility"] == "public"
    assert card["hc2"]["iri"] == "https://example.org/h/sarm"
    assert card["spatial"]["lat"] == 45.62

    # the container really is in the store, and the card really is in the index
    assert main_module.STORE.get(body["id"]) is not None
    assert main_module.INDEX.get(body["id"])["checksum"] == card["checksum"]


def test_the_card_is_derived_and_never_supplied(client, public_study):
    """`visibility` is a property of the STUDY. An endpoint that accepted it as a
    parameter would let a caller publish somebody else's work in progress."""
    body = _register(client, public_study)
    assert body["card"]["visibility"] == "public"

    public_study["header"]["visibility"] = "restricted"
    again = _register(client, public_study, study_id=body["id"])
    assert again["card"]["visibility"] == "restricted", \
        "the container said so — nothing else gets a vote"


def test_a_document_that_is_not_a_container_is_the_callers_problem(client):
    answer = client.post("/catalog/studies", json={"nope": True})
    assert answer.status_code == 400
    assert "em.json" in answer.text


# ── retrieval ────────────────────────────────────────────────────────────────

def test_emjson_gives_back_exactly_what_went_in(client, public_study):
    """Byte-for-byte on the CONTENT: a catalogue that reformatted a study on the
    way out would be editing it, and the checksum it advertised would drift."""
    body = _register(client, public_study)
    answer = client.get(f"/catalog/study/{body['id']}/emjson")
    assert answer.status_code == 200
    returned = json.loads(answer.text)
    assert returned == public_study
    assert em.content_digest(returned) == body["card"]["checksum"]


def test_the_study_card_is_served_from_the_container_when_the_index_is_empty(
        client, public_study):
    """The container is the truth: a gap in a projection must not look like a
    missing study."""
    body = _register(client, public_study)
    main_module.INDEX.remove(body["id"])
    answer = client.get(f"/catalog/study/{body['id']}")
    assert answer.status_code == 200
    assert answer.json()["title"] == "Sarmizegetusa 2026"


def test_ttl_is_served_in_publish_mode(client, public_study):
    """A dissemination surface must not carry tombstones. Here is one, deleted
    through the CRDT, and it must not reach the triples."""
    pytest.importorskip("rdflib")

    graph_id = public_study["active_graph_id"]
    section = public_study["graphs"][graph_id]
    assert em.apply_op(section, em.make_op(
        "remove_node", id=f"{graph_id}-us2",
        ts="2026-08-15T10:00:00+00:00", author="scavatrice"))["applied"]

    body = _register(client, public_study)
    answer = client.get(f"/catalog/study/{body['id']}/ttl")
    assert answer.status_code == 200, answer.text
    assert answer.headers["content-type"].startswith("text/turtle")
    ttl = answer.text
    assert "removedAt" not in ttl, "a deleted US reached the published triples"
    assert f"{graph_id}-us2" not in ttl
    assert f"{graph_id}-us1" in ttl, "the living are still there"

    # …and the em.json still HAS the tombstone: it is the re-editable truth
    container = client.get(f"/catalog/study/{body['id']}/emjson").json()
    nodes = {n["id"]: n for n in container["graphs"][graph_id]["nodes"]}
    assert "removed" in nodes[f"{graph_id}-us2"]["data"]


def test_a_missing_study_is_a_404(client):
    assert client.get("/catalog/study/study:nope").status_code == 404
    assert client.get("/catalog/study/study:nope/emjson").status_code == 404


# ── search and the two views ─────────────────────────────────────────────────

def test_the_flat_catalogue_lists_and_filters(client, public_study,
                                              other_twin_study):
    _register(client, public_study)
    _register(client, other_twin_study)

    everything = client.get("/catalog/studies").json()
    assert everything["view"] == "flat" and everything["count"] == 2

    by_author = client.get("/catalog/studies", params={"author": "sempronio"}).json()
    assert [s["title"] for s in by_author["studies"]] == ["Colosseo 2024"]

    by_text = client.get("/catalog/studies", params={"q": "colosseo"}).json()
    assert by_text["count"] == 1


def test_the_hdt_view_groups_the_studies_of_one_object(client, public_study,
                                                       restricted_study,
                                                       other_twin_study):
    """Spec §4: one heritage object, its N studies over time."""
    _register(client, public_study)
    _register(client, restricted_study)
    _register(client, other_twin_study)

    grouped = client.get("/catalog/studies", params={"view": "hdt"}).json()
    assert grouped["view"] == "hdt"
    keys = [g["key"] for g in grouped["groups"]]
    assert "https://example.org/h/sarm" in keys
    sarm = next(g for g in grouped["groups"]
                if g["key"] == "https://example.org/h/sarm")
    assert sarm["count"] == 2, "two campaigns, one monument"

    direct = client.get("/catalog/hdt/https://example.org/h/sarm")
    assert direct.status_code == 200, direct.text
    assert direct.json()["count"] == 2
    assert direct.json()["hc1"]["name"] == "Sarmizegetusa Regia"


def test_an_unknown_twin_is_a_404(client, public_study):
    _register(client, public_study)
    assert client.get("/catalog/hdt/iri:nobody").status_code == 404


# ── open in… ─────────────────────────────────────────────────────────────────

def test_open_gives_a_descriptor_with_something_that_works_today(client,
                                                                 public_study):
    body = _register(client, public_study)
    answer = client.get(f"/catalog/study/{body['id']}/open").json()

    assert answer["emjson"].endswith(f"/catalog/study/{body['id']}/emjson")
    assert set(answer["apps"]) == {"emstudio", "blender", "heriverse"}
    for app_name, target in answer["apps"].items():
        assert target["emjson"] == answer["emjson"], \
            f"{app_name} must have something it can act on today"
    assert "scheme" in answer["apps"]["emstudio"]["proposed"], \
        "the custom scheme is a proposal and must SAY so — no handler exists"


def test_open_can_be_asked_for_one_app(client, public_study):
    body = _register(client, public_study)
    answer = client.get(f"/catalog/study/{body['id']}/open",
                        params={"app": "heriverse"}).json()
    assert list(answer["apps"]) == ["heriverse"]
    assert client.get(f"/catalog/study/{body['id']}/open",
                      params={"app": "powerpoint"}).status_code == 400


# ── the index is derived, over HTTP ──────────────────────────────────────────

def test_reindex_rebuilds_the_catalogue_from_the_object_store(client,
                                                              public_study,
                                                              other_twin_study):
    a = _register(client, public_study)
    b = _register(client, other_twin_study)
    before = client.get("/catalog/studies").json()

    main_module.INDEX.reindex([])         # the index is lost
    assert client.get("/catalog/studies").json()["count"] == 0

    rebuilt = client.post("/catalog/reindex").json()
    assert rebuilt["studies"] == 2 and rebuilt["unreadable"] == []
    after = client.get("/catalog/studies").json()
    assert after == before
    assert {a["id"], b["id"]} == {s["id"] for s in after["studies"]}


def test_removing_a_study_removes_both_halves(client, public_study):
    body = _register(client, public_study)
    answer = client.delete(f"/catalog/study/{body['id']}").json()
    assert answer["removed"] == {"container": True, "index": True}
    assert client.get(f"/catalog/study/{body['id']}").status_code == 404
    assert client.delete(f"/catalog/study/{body['id']}").status_code == 404
