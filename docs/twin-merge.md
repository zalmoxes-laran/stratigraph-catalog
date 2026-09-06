# Merging two twins — decided, and built as an alias

> ## THE DECISION · 1 October 2026 · E.D.
>
> **Alias only. No document is ever touched.**
>
> The reason is ownership before it is technique, and it is §1 below: the
> documents carrying the losing key belong to **other people** — some published
> and immutable, some on a laptop in a trench with no network, some belonging to
> a project that ended. A merge that had to edit them could only ever
> half-happen, **and a half-merge is worse than two twins, because it looks
> finished.**
>
> The experimental confirmation that closed it is §5: the CRDT records **when**
> and **by whom**, never **what was there before**. The superseded value lives
> only in `FieldOutcome.loser_value`, which is a report and not a record — so
> rewriting a key inside a document would be a one-way door.
>
> Built on 1 October 2026: `app/aliases.py`, `POST /catalog/twins/merge`,
> `POST /catalog/twins/unmerge`, `GET /catalog/twins/aliases`, and the alias
> applied in one place (`index.hdt_key`).

*30 September 2026. Written after building the twin register (`app/twins.py`),
and deliberately stopping before the merge. Everything below was measured
against the code that exists, not imagined: where a claim comes from a
measurement, the measurement is named. The sections are kept as they were
written; where the build answered one of them, it says so.*

Two people excavate the same monument, neither knows about the other, and each
makes their own digital twin. That is not a mistake — it is the correct outcome
of two honest processes, and the register exists so it can be **repaired
afterwards** rather than prevented beforehand. Preventing it would mean forcing
the choice up front, which is the one thing this whole design refuses.

So: **the register's job is not to stop you making a twin. It is to let two of
them become one later.**

---

## 0 · What a merge is a statement about

Not about nodes. About **keys**.

Measured in `s3dgraphy/crdt.py`: `merge_payloads(mine, theirs)` merges two
payloads **of the same node**, keyed by `id`
(`node_id = str(mine.get("id") or theirs.get("id"))`). Two twins made in two
documents have two different uuids and are never the same node — no amount of
CRDT merging will ever bring them together, and it is not supposed to.

Measured too: the op vocabulary is five verbs —
`("add_node", "update_field", "remove_node", "add_edge", "remove_edge")`. **None
of them renames a node or aliases an identity.** There is no `rename` and no
`alias`, and adding one would be a change to the wire contract, which is not a
thing to do casually and not a thing to do for this.

What the Catalog actually groups on is neither of those: it is
`hc2.iri or hc2.id` (`app/index.py::group_by_hdt`), i.e. the **shared key** —
`heritage_entity_iri` on the twin node, when there is one. So:

> A merge is a statement that **two keys name one twin**. It is a fact about the
> register, not an edit of anybody's graph.

---

## 1 · What must happen to nodes

**Nothing.** No node is renamed, deleted or rewritten.

That is a design choice and not laziness, and the reason is ownership: the
documents carrying the losing key belong to **other people**. Some are
published and meant to be immutable, some are on a laptop in a trench with no
network, and some belong to a project that ended. A merge that required editing
them would be a merge that can only ever half-happen — and a half-merge is worse
than two twins, because it looks finished.

---

## 2 · What must happen to edges

**Nothing, and this is the easy part** — easy because of a decision already
made. The two edges the attribution authors are

    HC1 ─has_digital_twin→ HC2 ─contains_proposition_set→ HC16

and **both are inside one document**. No edge in this model crosses documents,
so nothing has to be re-pointed when two twins become one. (Verified against
`DocumentStore.applyHdto` in EMStudio: the only edges it writes are those two,
plus the study's own.)

---

## 3 · What must happen to studies already published under the old key

They stay exactly as they are, and the register resolves both keys to one group.
Three things are needed, and one of them is a trap:

1. **The alias must live where `reindex` cannot erase it.**
   Measured: `SqliteCatalogIndex.reindex` does `DELETE FROM studies` and rebuilds
   the whole index from the cards, and the cards are derived from the containers.
   **Anything recorded only in the index disappears on the next rebuild** — and
   `reindex` is not an emergency procedure here, it is the ordinary way this
   service repairs itself. So the alias table belongs in the **object store**,
   beside the containers, and is read at startup and after a rebuild.

2. **The alias must be applied in exactly ONE place.** The key is derived in
   `group_by_hdt` (and in `_hdt_keys` for the index columns, and in
   `hc1_keys`…). Canonicalising in three places is how two of them end up
   disagreeing. One function, `canonical_key(key)`, called where the key is
   first read.

3. **`/hdt/{loser}` must answer, and must say what happened.** Not a 404 (a
   study's twin has not stopped existing) and not a silent redirect (a caller
   who bookmarked the old key deserves to know it moved). It answers with the
   merged group and a `merged_into` field.

---

## 4 · What happens to somebody who was disconnected when the merge happened

They keep working on the losing key, and everything keeps working: their next
publish carries the old key, and the register maps it. **A merge never breaks an
offline editor** — which is precisely the property that makes it safe to perform
at all, and it follows from §1 (no document is edited).

When they reconnect, the panel can say *«this twin has been merged into X»* and
offer to adopt the winning key. **Offer.** Adopting is an ordinary field write
with a clock, and it is a decision, not a migration — the same rule as the
search itself: suggest, never gate. A tool that silently rewrote the key in
somebody's document while they were away would be doing exactly what §1 says a
merge must never do, only more quietly.

---

## 5 · REVERSIBILITY — the part to read twice

**An alias-only merge is reversible.** Delete the alias and the two groups are
two again, because nothing else changed. This is the whole argument for doing it
this way.

**A merge that rewrites the key inside a document is NOT reversible with what
the CRDT stores.** Measured in `crdt.py`:

* `write_field` / `set_field` replace the value; `set_field_clock` records *when*
  and *by whom*, never *what it was before*;
* the previous value survives in exactly one place — `FieldOutcome.loser_value`,
  which `merge_payloads` **returns to the caller** as part of a `MergeOutcome`.
  That is a **report, not a record**: nothing in the document persists it, and
  once the caller has printed it, it is gone.

So, in one sentence, and it is the most important sentence in this file:

> **If a merge is ever allowed to touch a document, the old key must be written
> down in the same act (`data.hdt_merged_from`), or the merge is a one-way
> door.**

The recommendation is therefore: **do not touch documents. Alias only.** And if
E.D. decides that documents may be rewritten — there are good reasons to want it,
e.g. a study that must carry the canonical key into a publication — then the
write and the record of what it replaced are **one act**, exactly as
`set_field` and `set_field_clock` were made one act in P4.1b for the same
reason.

**Decided on 1 October 2026: alias only.** Documents are not rewritten, so the
one-way door is never opened. If that is ever revisited, the condition above
stands and is not negotiable: the write and the record of what it replaced must
be **one act**.

---

## 6 · What a merge needed before it could be built — and where each one landed

*Built 1 October 2026. Each line now names the thing that answers it.*

| requirement | where it is |
|---|---|
| a durable home for the alias table | `registry/twin-aliases.json` in the **object store**, read at startup and re-read by `reindex` (`app/aliases.py`) |
| `canonical_key()` applied in one place | `index.hdt_key()`, called by `group_by_hdt` **and** `_hdt_keys` — the two places that used to derive it |
| who may merge, recorded | `POST /catalog/twins/merge` on the authenticated router; the author comes from the TOKEN, never the body |
| the un-merge as a first-class action | `aliases.unmerge` / `POST /catalog/twins/unmerge` |
| `/hdt/{loser}` says what happened | 200 with `merged_into`, `merged_by`, `merged_at` — not a 404, not a silent redirect |
| the panel side | **NOT built** — it is EMStudio's, and it has its own moment |
| a rule for merging two provisionals | below, and there is nothing to build |

### Merging two provisionals

Neither has a shared key, so there is nothing to alias. The rule, written down
so nobody invents a second mechanism for it:

> One of them has to acquire a key first. **A merge of two provisionals is a
> registration followed by an alias** — the two operations that already exist,
> in that order.

### The original list



* a durable home for the alias table (an object-store prefix beside the
  containers, read at startup and after `reindex`);
* `canonical_key()` applied in one place;
* **who may merge**: it is an editorial act on shared identity, so an
  authenticated one, with the decider recorded — and a merge whose author is
  unknown is one nobody can argue with later;
* **the un-merge as a first-class action**, not a database repair. A reversible
  operation whose reversal is a manual `DELETE` is reversible only in theory;
* the panel side: *«merged into X»*, an offer to adopt, and never an automatic
  rewrite;
* a rule for **merging two provisionals** (neither has a shared key): one of
  them has to acquire one first, which means a merge of two provisionals is a
  *registration* followed by an alias, and saying so avoids inventing a second
  mechanism.

## 7 · One thing s3Dgraphy would have to add, and it is small

The twin's declared state already survives the whole round trip. Measured on a
live service, 30 September 2026: an EMStudio document whose twin carries
`hdt_status: "registered"` and `hdt_registry: {...}` comes back out of
`parse_container` with both intact — the importer keeps data keys it does not
know.

What does **not** reach the catalogue is the state itself, because
`s3dgraphy/study.py::_hdt_of` builds `hc2` out of three fields only
(`id`, `name`, `heritage_entity_iri`). So today the register derives
«provisional» from the ABSENCE of a shared key, which is equivalent by
construction (EMStudio enforces `registered ⟺ key`, guarded in
`frontend/scripts/check-hdt.mjs`) — but a document written by a tool that does
not enforce it would be read charitably rather than accurately.

The ask, when somebody is next in that file: let `_hdt_of` carry
`hdt_status` and (once merges exist) `hdt_merged_from` onto the `hc2` dict. Two
lines, and it turns a derivation into a record.

**Done, 1 October 2026** — two lines in `src/s3dgraphy/study.py::_hdt_of`, on
`s3dgraphy_v1.6dev` (that file does not exist on `main`; see the report). The
card's `hc2` now carries `hdt_status` and `hdt_merged_from`, and the catalogue
reads a record instead of inferring one from an absence.
