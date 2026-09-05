"""The TWIN REGISTRY — «which digital twins do I know», asked of several places.

The catalogue already answered *«which studies does this twin have»*
(``/hdt/{hc2}``). This is the other direction, and it is the one somebody
standing in an excavation needs: **I have found something; is there already a
twin for it, or am I the first?**

## It suggests, it does not gate

Nothing here is a precondition for working. A study with no twin is a citizen —
:func:`app.index.group_by_hdt` has kept its homeless bucket from the first day
for exactly this reason — and the registry says how many of them there are
(``untwinned``) rather than treating them as a gap to be closed. An excavator
who does not yet know what they are digging must be able to say so and carry on;
a tool that forces the answer collects a lie, and a lie put in a required field
outlives the truth it replaced.

## Three facts per twin, and why those three

A twin result carries **where it came from** (``source``), **who holds it**
(``custodians``) and **how many studies hang on it** (``studies``). Attaching to
the wrong twin is worse than minting a new one — a new one can be merged later,
a wrong attachment quietly puts your excavation inside somebody else's monument
— and none of the three is decorative:

* the *source* is which register answered, because tomorrow there are two;
* the *custodians* are the people already working on it, which is what tells a
  reader whether this is the twin their colleague made last month;
* the *count* separates a twin with fifteen campaigns behind it from one
  somebody created yesterday and abandoned.

**``custodians`` is derived from the AUTHORS of the studies indexed under the
twin**, and says so in the payload (``custodians_from``). It is not a custody
field: nothing in the card records one. Naming the derivation is the difference
between an honest answer and an invented one.

## The merge is designed and not built

Two twins for one monument is the correct outcome of two honest processes, and
this register exists so it can be repaired afterwards rather than prevented
beforehand. **How that repair must work — and the one way of doing it that
cannot be undone — is in ``docs/twin-merge.md``.** Read it before writing any
code that makes two keys into one.

## Provisional twins are visible AS provisional

A twin whose identity is only the node id its document minted (no IRI) is
**provisional**: it exists, it is findable, and nobody else can have named the
same key on purpose. One that carries an IRI is a **registered** identity that
two catalogues can agree on. The registry marks the difference (``provisional``)
instead of hiding it, because a provisional twin belonging to somebody else is
precisely the twin you should NOT attach yourself to.

## Federated from birth, with one source built

The answer always carries a ``sources`` list, every result names the source it
came from, and today exactly one source answers. That shape is not decoration:
a search written against a single register and federated later becomes two
implementations that disagree — this project has paid that bill once already
(the queue that existed for the browser and not for the service).

**The collaborative cloud is DECLARED, not simulated.** It appears in
``sources`` with ``status: "not_configured"`` and a sentence, and it returns
nothing, ever. A mock that looked like a second register would make the day it
arrives indistinguishable from the day before it.

Adding it tomorrow, in three lines:

    class CloudTwinSource:                 # 1 · id/kind/label + describe()
        def search(self, query, limit): ...  # 2 · returns twins, each with
                                             #     "source": self.id
    SOURCES.append(CloudTwinSource(url))   # 3 · in sources_from_env()
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional, Protocol

from .index import group_by_hdt, group_label

#: What a source says about itself when it cannot answer. Kept as words rather
#: than booleans because a caller has to be able to PRINT the reason.
STATUS_OK = "ok"
STATUS_NOT_CONFIGURED = "not_configured"

#: The default number of twins returned. A registry answer is read by a person
#: choosing one, not by a machine paging through them.
DEFAULT_LIMIT = 20


class TwinSource(Protocol):
    """A place that can be asked «which twins do you know».

    Three members and one method. The narrowness is the point: the second
    implementation must be able to exist without this file changing.
    """

    id: str
    kind: str
    label: str

    def describe(self) -> Dict[str, Any]:
        """`{id, kind, label, status, detail?}` — always answered, including
        (especially including) when the source cannot answer a search."""

    def search(self, query: str = "", limit: int = DEFAULT_LIMIT
               ) -> List[Dict[str, Any]]:
        """The twins this source knows, each one carrying `source: self.id`."""


# ── the one that is actually built ───────────────────────────────────────────

class LocalCatalogSource:
    """This catalogue's own index, read as a register of twins.

    It is handed a CALLABLE returning the cards the asker may see, rather than
    the index itself: the visibility rule (public unless authenticated, embargo
    included) lives in one readable line in `main.py` and must not be
    re-implemented here. A register that leaked the existence of somebody's
    unpublished twin would be a worse failure than not having a register.
    """

    id = "catalog"
    kind = "catalog"

    def __init__(self, cards: Callable[[], List[Dict[str, Any]]],
                 label: str = "this catalogue") -> None:
        self._cards = cards
        self.label = label

    def describe(self) -> Dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "label": self.label,
                "status": STATUS_OK}

    def search(self, query: str = "", limit: int = DEFAULT_LIMIT
               ) -> List[Dict[str, Any]]:
        return twins_of(self._cards(), query=query, limit=limit,
                        source=self.id)


# ── the one that is declared and not built ───────────────────────────────────

class DeclaredSource:
    """A register named in the answer and not implemented — on purpose.

    It returns nothing and says why, in the tone the authority badge already
    uses for its own absence («resolver unavailable»). A caller can therefore
    tell «nobody has a twin for this» apart from «I only asked one of the two
    places», which is the distinction a mock would destroy.
    """

    def __init__(self, source_id: str, kind: str, label: str,
                 detail: str) -> None:
        self.id = source_id
        self.kind = kind
        self.label = label
        self.detail = detail

    def describe(self) -> Dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "label": self.label,
                "status": STATUS_NOT_CONFIGURED, "detail": self.detail}

    def search(self, query: str = "", limit: int = DEFAULT_LIMIT
               ) -> List[Dict[str, Any]]:
        return []


CLOUD_DETAIL = (
    "the collaborative cloud is not part of this deployment yet: this "
    "answer names the twins THIS catalogue knows, and no others"
)


def sources_from_env(cards: Callable[[], List[Dict[str, Any]]],
                     environ: Optional[Dict[str, str]] = None
                     ) -> List[TwinSource]:
    """The registers to ask, in order. One real, one declared absent.

    `EM_CATALOG_LABEL` names this catalogue in the answer, so a reader looking
    at a result from a federated search can tell which institution's register
    it came from. Unset, it says «this catalogue», which is true and useless in
    exactly the situation where nothing else is federated with it.
    """
    env = dict(environ if environ is not None else os.environ)
    label = (env.get("EM_CATALOG_LABEL") or "").strip() or "this catalogue"
    return [
        LocalCatalogSource(cards, label=label),
        DeclaredSource("cloud", "collaborative-cloud",
                       "StratiGraph collaborative cloud", CLOUD_DETAIL),
    ]


# ── turning cards into twins ─────────────────────────────────────────────────

def _matches(twin: Dict[str, Any], query: str) -> bool:
    """Free text over what somebody would actually type: the twin's name, the
    entity's name, and either identity. An empty query matches everything —
    «show me what you have» is a question a register must answer."""
    if not query:
        return True
    needle = query.strip().lower()
    if not needle:
        return True
    hay: List[str] = [str(twin.get("label") or ""), str(twin.get("key") or "")]
    for entity in (twin.get("hc2"), twin.get("hc1")):
        if isinstance(entity, dict):
            hay.extend(str(entity.get(k) or "") for k in ("name", "iri", "id"))
    return needle in " ".join(hay).lower()


#: s3Dgraphy's sentinel for «this author has no ORCID» (`AuthorNode`'s default,
#: and the rdf_exporter already refuses to publish it as an identity). It must be
#: read as ABSENT here too — measured on a live catalogue, 30 September 2026,
#: where it arrived as an author's `orcid` and would have made every unidentified
#: person on a monument dedupe into ONE custodian.
NO_ORCID = "noorcid"


def _orcid_of(author: Dict[str, Any]) -> str:
    value = str(author.get("orcid") or "").strip()
    return "" if value.lower() == NO_ORCID else value


def custodians_of(studies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Who is already working on this twin — the authors of its studies.

    De-duplicated on the ORCID when there is a REAL one and on the name
    otherwise, so the same person recorded twice does not read as two teams —
    and so two different people who both lack an ORCID do not read as one.
    Deliberately NOT ranked or truncated here: the caller printing three of them
    can take three, and a registry that pre-decided which custodian mattered
    would be making an editorial judgement in a lookup.
    """
    out: List[Dict[str, Any]] = []
    seen = set()
    for card in studies:
        for author in card.get("authors") or []:
            if not isinstance(author, dict):
                continue
            name = str(author.get("name") or "").strip()
            orcid = _orcid_of(author)
            if not name and not orcid:
                continue
            key = orcid or name.lower()
            if key in seen:
                continue
            seen.add(key)
            entry: Dict[str, Any] = {"name": name or None}
            if orcid:
                entry["orcid"] = orcid
            out.append(entry)
    return out


def is_provisional(twin_entity: Optional[Dict[str, Any]]) -> bool:
    """A twin with no IRI is provisional — known only by the id its own
    document minted.

    Not a judgement about the work: a provisional twin is a legitimate and
    ordinary thing to have made, and it is what somebody who did not yet know
    what they were digging correctly produced. It is a statement about the
    IDENTITY: nobody else can have meant the same key, so two provisional twins
    of one monument are two records until somebody merges them.
    """
    if not isinstance(twin_entity, dict):
        return True
    return not str(twin_entity.get("iri") or "").strip()


def twins_of(cards: List[Dict[str, Any]], *, query: str = "",
             limit: int = DEFAULT_LIMIT, source: str = "catalog"
             ) -> List[Dict[str, Any]]:
    """The twins a set of cards knows about, as register entries.

    Built on `group_by_hdt`, which is already the catalogue's one reading of
    «which studies belong to which twin». A second grouping written here would
    be a second answer to a question that has one.
    """
    entries: List[Dict[str, Any]] = []
    for group in group_by_hdt(cards):
        if group.get("key") is None:
            continue                      # the homeless: counted, not a twin
        studies = group.get("studies") or []
        entry = {
            "key": str(group["key"]),
            "label": group.get("label") or group_label(group),
            "source": source,
            "hc2": group.get("hc2"),
            "hc1": group.get("hc1"),
            "studies": len(studies),
            "custodians": custodians_of(studies),
            #: named, because a derivation presented as a record is a lie that
            #: reads as data
            "custodians_from": "study-authors",
            "provisional": is_provisional(group.get("hc2")),
            "study_ids": [c.get("id") for c in studies if c.get("id")],
        }
        if _matches(entry, query):
            entries.append(entry)
    # most-studied first: the twin fifteen campaigns hang on is the one somebody
    # searching for a monument almost always means. Ties by label, so the answer
    # is stable across two calls (a register whose order moves is a register a
    # person cannot point at).
    entries.sort(key=lambda e: (-e["studies"], e["label"], e["key"]))
    return entries[: max(1, int(limit))]


def untwinned_count(cards: List[Dict[str, Any]]) -> int:
    """How many studies have no twin yet — a REAL bucket, and the first thing a
    curator asks. Reported beside the twins rather than as a warning: not
    knowing yet is a state, not a defect."""
    for group in group_by_hdt(cards):
        if group.get("key") is None:
            return len(group.get("studies") or [])
    return 0


def search_twins(sources: List[TwinSource], *, query: str = "",
                 limit: int = DEFAULT_LIMIT) -> Dict[str, Any]:
    """Ask every register, keep the answers apart, and say who answered.

    The shape is the federated one from the first line of code: `sources` always
    lists every register that was asked and what it said about itself, and each
    twin names the one it came from. With one source built, that costs a list
    of one; with two it costs nothing to add.
    """
    described: List[Dict[str, Any]] = []
    found: List[Dict[str, Any]] = []
    for source in sources:
        report = dict(source.describe())
        answers = source.search(query=query, limit=limit)
        report["count"] = len(answers)
        described.append(report)
        found.extend(answers)
    found.sort(key=lambda e: (-e["studies"], e["label"], e["key"]))
    return {"query": query, "sources": described,
            "count": len(found), "twins": found[: max(1, int(limit))]}
