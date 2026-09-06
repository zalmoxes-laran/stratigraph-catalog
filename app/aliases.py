"""Twin aliases — the statement that two keys name one twin.

E.D.'s decision, 1 October 2026: **alias only. No document is ever touched.**
The argument is in ``docs/twin-merge.md`` and it is about ownership before it is
about technique — the documents carrying the losing key belong to other people,
some published and immutable, some on a laptop in a trench with no network. A
merge that had to edit them could only ever half-happen, **and a half-merge is
worse than two twins, because it looks finished.**

    A merge is a fact about the REGISTER, not a modification of anybody's graph.

── WHERE THIS LIVES, AND WHY IT IS THE MOST IMPORTANT LINE IN THE FILE ────────

In the **object store**, beside the containers — never in the index.

``SqliteCatalogIndex.reindex`` does ``DELETE FROM studies`` and rebuilds every
row from the cards, which derive from the containers. Anything that lived only
in the index would vanish at the next rebuild — and ``reindex`` is not an
emergency procedure, it is **the ordinary way this service repairs itself**. An
alias that did not survive it would be an alias that quietly stops being true.

So: ``registry/twin-aliases.json``, under a prefix that ``store.list()`` does not
match, read at startup and after every rebuild.

── REVERSIBILITY ──────────────────────────────────────────────────────────────

``unmerge`` is a function with a name, not a manual ``DELETE``: *an operation
whose reversal is a hand-edit is reversible only in theory.* Because nothing but
this table ever changed, un-merging restores the register **exactly** — and the
tests check that byte for byte on the grouping, not by inspection.

── WHAT IS NOT HERE ───────────────────────────────────────────────────────────

Merging two PROVISIONALS (neither has a shared key). The rule, written down so
nobody invents a second mechanism for it: one of them has to acquire a key
first, so that merge is **a registration followed by an alias** — the two things
that already exist, in that order. There is nothing to build.
"""

from __future__ import annotations

import json
import threading
from typing import Any, Dict, List, Optional

from .store import REGISTRY_PREFIX

#: The one object this module owns.
ALIAS_KEY = f"{REGISTRY_PREFIX}twin-aliases.json"

#: Format marker, so a file written by a future version can be recognised rather
#: than silently misread.
ALIAS_FORMAT = "em-catalog/twin-aliases@1"


class AliasError(ValueError):
    """A merge that was refused, with the sentence saying why."""


#: The loaded table: `losing key -> {merged_into, by, at}`. Module-level and
#: guarded, because `canonical_key` is called from the grouping code on every
#: card and must not take a round trip to the store to answer.
_TABLE: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.Lock()


def table() -> Dict[str, Dict[str, Any]]:
    """A copy of the loaded table — callers get facts, not the mutable dict."""
    with _LOCK:
        return {k: dict(v) for k, v in _TABLE.items()}


def canonical_key(key: Optional[str]) -> Optional[str]:
    """The key this one has been merged into, following the chain.

    **The single place an alias is applied.** The HC2 key is derived in more
    than one spot (`group_by_hdt`, `_hdt_keys`), and canonicalising in each of
    them is how two of them end up disagreeing — so they all call `index.hdt_key`,
    which calls this.

    A chain is followed to its fixed point (a→b, b→c ⇒ a→c) and a cycle is
    survived rather than hung on: a table that somehow contained one would
    otherwise take the whole catalogue down, and the register being slightly
    wrong is better than the register being unreachable.
    """
    if not key:
        return None
    current = str(key)
    seen = {current}
    with _LOCK:
        for _ in range(len(_TABLE) + 1):
            nxt = _TABLE.get(current, {}).get("merged_into")
            if not nxt or str(nxt) in seen:
                break
            current = str(nxt)
            seen.add(current)
    return current


def merged_from(key: Optional[str]) -> List[str]:
    """Every key that resolves INTO this one — what the winner absorbed."""
    if not key:
        return []
    target = str(key)
    with _LOCK:
        losers = list(_TABLE)
    return sorted(k for k in losers if canonical_key(k) == target and k != target)


def entry(key: Optional[str]) -> Optional[Dict[str, Any]]:
    """The alias record for a losing key, or None if it is not one."""
    if not key:
        return None
    with _LOCK:
        found = _TABLE.get(str(key))
        return dict(found) if found else None


# ── persistence ──────────────────────────────────────────────────────────────

def load(store: Any) -> Dict[str, Dict[str, Any]]:
    """Read the table from the object store into memory. Returns it."""
    raw = None
    try:
        raw = store.get_blob(ALIAS_KEY)
    except Exception:                      # a store without blobs, or offline
        raw = None
    parsed: Dict[str, Dict[str, Any]] = {}
    if raw:
        try:
            doc = json.loads(raw.decode("utf-8"))
            if isinstance(doc, dict) and doc.get("format") == ALIAS_FORMAT:
                for loser, record in (doc.get("aliases") or {}).items():
                    if isinstance(record, dict) and record.get("merged_into"):
                        parsed[str(loser)] = {
                            "merged_into": str(record["merged_into"]),
                            "by": record.get("by"),
                            "at": record.get("at"),
                        }
        except (ValueError, AttributeError):
            # A register file we cannot read is NOT treated as an empty one:
            # that would silently un-merge everything. Say so and keep what is
            # already in memory.
            raise AliasError(f"{ALIAS_KEY} is not a readable alias table")
    with _LOCK:
        _TABLE.clear()
        _TABLE.update(parsed)
    return table()


def save(store: Any) -> Dict[str, Any]:
    """Write the in-memory table back to the object store."""
    with _LOCK:
        doc = {"format": ALIAS_FORMAT,
               "aliases": {k: dict(v) for k, v in sorted(_TABLE.items())}}
    data = json.dumps(doc, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    return store.put_blob(ALIAS_KEY, data)


def reset() -> None:
    """Forget the loaded table — for tests, and for a store that changed."""
    with _LOCK:
        _TABLE.clear()


# ── the two acts ─────────────────────────────────────────────────────────────

def merge(store: Any, loser: str, winner: str, *, author: str,
          at: Optional[str] = None) -> Dict[str, Any]:
    """Declare that `loser` names the same twin as `winner`.

    The author is required and not defaulted: **a merge without an author is a
    merge nobody can argue with afterwards**, and this is an editorial act on
    shared identity.
    """
    loser, winner = str(loser or "").strip(), str(winner or "").strip()
    if not loser or not winner:
        raise AliasError("a merge needs both keys")
    if loser == winner:
        raise AliasError("a key cannot be merged into itself")
    if not str(author or "").strip():
        raise AliasError("a merge needs an author")

    # Resolve the winner first: merging into a key that is itself merged should
    # land on the twin that actually survives, not build a chain by accident.
    target = canonical_key(winner) or winner
    if target == loser:
        raise AliasError(
            f"{winner!r} already resolves to {loser!r} — merging would make a cycle")
    existing = entry(loser)
    if existing and existing.get("merged_into") == target:
        return {"loser": loser, "merged_into": target, "created": False,
                "by": existing.get("by"), "at": existing.get("at")}
    if existing:
        raise AliasError(
            f"{loser!r} is already merged into {existing['merged_into']!r} — "
            "un-merge it first, so the change is two acts and not a silent one")

    stamp = at or _now()
    with _LOCK:
        _TABLE[loser] = {"merged_into": target, "by": str(author), "at": stamp}
    save(store)
    return {"loser": loser, "merged_into": target, "created": True,
            "by": str(author), "at": stamp}


def unmerge(store: Any, loser: str) -> Dict[str, Any]:
    """Take the alias back. The register returns to exactly what it was."""
    loser = str(loser or "").strip()
    with _LOCK:
        removed = _TABLE.pop(loser, None)
    if removed is None:
        raise AliasError(f"{loser!r} is not merged into anything")
    save(store)
    return {"loser": loser, "was_merged_into": removed.get("merged_into"),
            "by": removed.get("by"), "at": removed.get("at")}


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
