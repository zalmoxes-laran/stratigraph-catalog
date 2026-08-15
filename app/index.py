"""The index — a PROJECTION of the containers, and never a second truth.

The one architectural claim of this service: **the studies are the containers in
the object store; the index is derived from them.** Everything follows from it —
the index may be dropped and rebuilt (`reindex`), it may be implemented in
SQLite for a laptop and CouchDB for the deployment, and it can never disagree
with the studies for long, because the studies are what it is made of.

That is also what keeps the contract portable, which is the point of a REFERENCE
implementation: 3DR's production catalogue will keep its records in the WP6
CouchDB beside the `scene` documents (spec §7), and the thing being reused is the
CARD (`s3dgraphy.api.study_metadata`) and this INTERFACE, not our storage.

Two implementations, one interface:

* **SQLite** (dev) — real queries, one file, nothing to provision. `search` is a
  real query and not a scan, so the shape of the filters is honest about what an
  index has to be able to do.
* **CouchDB** (deploy) — behind the same interface, **config-gated exactly like
  the MinIO store**: it is used when it is configured, and never chosen silently.
  A catalogue that half-fell-back to a local file while its operator believed
  the records were in CouchDB is the failure this arrangement exists to prevent.

The card is stored **whole** (the JSON of `study_metadata`) plus the handful of
columns worth querying on. Storing only the columns would make the index a lossy
copy of the container, and lossy copies are how projections turn into truths.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Protocol

#: What `search` understands. Named here so the two implementations answer the
#: same questions, and so a caller can be told what it may ask.
FILTERS = ("q", "author", "orcid", "license", "hc2", "hc1", "visibility")


class CatalogIndex(Protocol):
    """Six methods. The sixth is the one that makes the other five safe."""

    def upsert(self, card: Dict[str, Any]) -> None:
        """Record (or replace) one study's card. Keyed by `card["id"]`."""

    def get(self, study_id: str) -> Optional[Dict[str, Any]]:
        """One card, or None."""

    def search(self, **filters: Any) -> List[Dict[str, Any]]:
        """Cards matching the filters (see :data:`FILTERS`); all of them if none."""

    def list(self, view: str = "flat") -> Any:
        """`flat` → the cards. `hdt` → them grouped by Heritage Digital Twin."""

    def remove(self, study_id: str) -> bool:
        """True when there was something to remove."""

    def reindex(self, cards: Any) -> int:
        """Replace the WHOLE index with these cards. Returns how many."""


# ── the two views ────────────────────────────────────────────────────────────

def group_by_hdt(cards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The HDT view (spec §4): one heritage object, its N studies over time.

    Grouped by HC2 identity, and the identity is the IRI when there is one —
    otherwise the node id. Two catalogues of the same monument that minted
    different node ids still belong together if they name the same IRI, and a
    grouping that only looked at ids would split them.

    Studies with no HDT are NOT dropped: they are gathered under a group whose
    key is `None`, because "which of my studies have no digital twin yet" is one
    of the first questions somebody curating a catalogue asks.
    """
    groups: Dict[Any, Dict[str, Any]] = {}
    for card in cards:
        hc2 = card.get("hc2") or None
        key = None
        if hc2:
            key = hc2.get("iri") or hc2.get("id")
        bucket = groups.setdefault(key, {
            "hc2": hc2, "hc1": card.get("hc1"), "studies": []})
        bucket["hc1"] = _better_entity(bucket["hc1"], card.get("hc1"))
        bucket["studies"].append(card)
    out = []
    for key, bucket in groups.items():
        bucket["key"] = key
        bucket["count"] = len(bucket["studies"])
        out.append(bucket)
    # named groups first, in a stable order; the homeless last
    out.sort(key=lambda g: (g["key"] is None, str(g["key"] or "")))
    return out


def _better_entity(current: Optional[Dict[str, Any]],
                   candidate: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Which of two HC1 records to show for a group — the more informative one.

    Not "the first one", and this is not a nicety. `study_metadata` falls back to
    an entity known only by the IRI its twin carries, so a campaign that never
    authored a `HeritageEntityNode` still produces an `hc1` — a dict with an IRI
    and no name. Keeping the first would let that stub outrank the study that
    actually names the monument, and the HDT view would show a group with no
    title while the name sat in the very next card. (Measured: it did, in
    `smoke_catalog.py`.)
    """
    if candidate is None:
        return current
    if current is None:
        return candidate

    def informative(entity: Dict[str, Any]) -> int:
        return sum(1 for key in ("name", "id", "kind", "iri")
                   if entity.get(key))

    return candidate if informative(candidate) > informative(current) else current


def _haystack(card: Dict[str, Any]) -> str:
    """The free-text field, built once at write time.

    Title, description, the authors' names, the site key and the twin's name:
    what somebody actually types when they are looking for a study. Built here
    rather than at query time because an index that has to open every card to
    answer a search is a scan wearing an index's clothes.
    """
    parts = [card.get("title"), card.get("description"), card.get("em_id")]
    for author in card.get("authors") or []:
        parts.append(author.get("name"))
        parts.append(author.get("orcid"))
    for key in ("hc1", "hc2"):
        node = card.get(key) or {}
        parts.append(node.get("name"))
        parts.append(node.get("iri"))
    for gid in card.get("graph_ids") or []:
        parts.append(gid)
    return " ".join(str(p) for p in parts if p).lower()


def _authors_blob(card: Dict[str, Any]) -> str:
    parts = []
    for author in card.get("authors") or []:
        parts.append(str(author.get("name") or ""))
        parts.append(str(author.get("orcid") or ""))
    return " ".join(p for p in parts if p).lower()


def _hdt_keys(card: Dict[str, Any]):
    hc2 = card.get("hc2") or {}
    hc1 = card.get("hc1") or {}
    hc2_key = hc2.get("iri") or hc2.get("id")
    hc1_key = hc1.get("iri") or hc1.get("id")
    return (str(hc2_key) if hc2_key else None,
            str(hc1_key) if hc1_key else None)


# ── SQLite: the dev index ────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS studies (
    id          TEXT PRIMARY KEY,
    card        TEXT NOT NULL,      -- the whole card, so the index is not lossy
    title       TEXT,
    haystack    TEXT,               -- free text, lowercased, built at write time
    authors     TEXT,
    license     TEXT,
    visibility  TEXT,
    hc2         TEXT,
    hc1         TEXT,
    checksum    TEXT
);
CREATE INDEX IF NOT EXISTS studies_hc2 ON studies(hc2);
CREATE INDEX IF NOT EXISTS studies_visibility ON studies(visibility);
"""


class SqliteCatalogIndex:
    """One file, real queries. The dev implementation, and it says so.

    `:memory:` is allowed and is what the tests use. The file one is what the
    dev-stack mounts on a volume — an index that vanished on every restart would
    make `reindex` look like a feature instead of a safety net.
    """

    def __init__(self, path: str = ":memory:") -> None:
        self.path = path
        # check_same_thread=False because uvicorn serves from a threadpool; every
        # write is behind the lock below, which is what actually makes it safe.
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(_SCHEMA)
            self._db.commit()

    # ── the interface ────────────────────────────────────────────────────────

    def upsert(self, card: Dict[str, Any]) -> None:
        study_id = card.get("id")
        if not study_id:
            raise ValueError("a card without an id cannot be indexed — the "
                             "catalogue owns the identity, and this one has none")
        hc2, hc1 = _hdt_keys(card)
        with self._lock:
            self._db.execute(
                "INSERT INTO studies (id, card, title, haystack, authors, "
                "license, visibility, hc2, hc1, checksum) "
                "VALUES (?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET card=excluded.card, "
                "title=excluded.title, haystack=excluded.haystack, "
                "authors=excluded.authors, license=excluded.license, "
                "visibility=excluded.visibility, hc2=excluded.hc2, "
                "hc1=excluded.hc1, checksum=excluded.checksum",
                (str(study_id), json.dumps(card, ensure_ascii=False),
                 card.get("title"), _haystack(card), _authors_blob(card),
                 card.get("license"), card.get("visibility"), hc2, hc1,
                 card.get("checksum")))
            self._db.commit()

    def get(self, study_id: str) -> Optional[Dict[str, Any]]:
        row = self._db.execute("SELECT card FROM studies WHERE id = ?",
                               (str(study_id),)).fetchone()
        return json.loads(row["card"]) if row else None

    def search(self, **filters: Any) -> List[Dict[str, Any]]:
        where: List[str] = []
        args: List[Any] = []
        text = (filters.get("q") or "").strip().lower()
        if text:
            where.append("haystack LIKE ?")
            args.append(f"%{text}%")
        for field, column in (("author", "authors"), ("orcid", "authors")):
            value = (filters.get(field) or "").strip().lower()
            if value:
                where.append(f"{column} LIKE ?")
                args.append(f"%{value}%")
        for field in ("license", "visibility"):
            value = (filters.get(field) or "").strip()
            if value:
                where.append(f"{field} = ?")
                args.append(value)
        for field in ("hc2", "hc1"):
            value = (filters.get(field) or "").strip()
            if value:
                where.append(f"{field} = ?")
                args.append(value)
        sql = "SELECT card FROM studies"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY title IS NULL, title, id"
        return [json.loads(row["card"])
                for row in self._db.execute(sql, args).fetchall()]

    def list(self, view: str = "flat") -> Any:
        cards = self.search()
        return group_by_hdt(cards) if view == "hdt" else cards

    def remove(self, study_id: str) -> bool:
        with self._lock:
            cursor = self._db.execute("DELETE FROM studies WHERE id = ?",
                                      (str(study_id),))
            self._db.commit()
            return cursor.rowcount > 0

    def reindex(self, cards: Any) -> int:
        """Replace the whole index. All or nothing, inside one transaction.

        Not "delete then insert one by one": a rebuild that failed halfway would
        leave a catalogue that has silently lost studies, which is the exact
        failure a rebuild exists to repair.
        """
        rows = list(cards)
        with self._lock:
            try:
                self._db.execute("BEGIN")
                self._db.execute("DELETE FROM studies")
                for card in rows:
                    study_id = card.get("id")
                    if not study_id:
                        continue
                    hc2, hc1 = _hdt_keys(card)
                    self._db.execute(
                        "INSERT INTO studies (id, card, title, haystack, "
                        "authors, license, visibility, hc2, hc1, checksum) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (str(study_id), json.dumps(card, ensure_ascii=False),
                         card.get("title"), _haystack(card), _authors_blob(card),
                         card.get("license"), card.get("visibility"), hc2, hc1,
                         card.get("checksum")))
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise
        return len([c for c in rows if c.get("id")])


# ── CouchDB: the deployment index, behind the same interface ─────────────────

class CouchDbCatalogIndex:
    """The WP6 index: a `study` document beside Heriverse's `scene` documents.

    Written against CouchDB's HTTP API with the standard library, because adding
    a client library to talk JSON over HTTP would be a dependency for a habit.

    **Config-gated, exactly like the MinIO store.** It is constructed only when
    the deployment names a CouchDB, and it never becomes the choice by accident.
    The constructor REACHES the server (`PUT` the database if missing) so a wrong
    URL or a wrong password is a startup failure with a sentence, not a 500 on
    somebody's first search.
    """

    #: The Mango index CouchDB needs to answer the HDT view without a full scan.
    _INDEXES = ({"index": {"fields": ["hc2"]}, "name": "by-hc2", "type": "json"},
                {"index": {"fields": ["visibility"]}, "name": "by-visibility",
                 "type": "json"})

    def __init__(self, url: str, database: str = "em-catalog",
                 user: str = "", password: str = "", *, timeout: int = 10) -> None:
        self.url = url.rstrip("/")
        self.database = database
        self.timeout = timeout
        self._auth = (user, password) if user else None
        self._ensure_database()

    # ── plumbing ─────────────────────────────────────────────────────────────

    def _request(self, method: str, path: str,
                 payload: Optional[Dict[str, Any]] = None,
                 *, expect: tuple = (200, 201, 202)) -> Any:
        target = f"{self.url}/{path.lstrip('/')}"
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(target, data=body, method=method)
        request.add_header("Accept", "application/json")
        if body is not None:
            request.add_header("Content-Type", "application/json")
        if self._auth:
            import base64
            token = base64.b64encode(
                f"{self._auth[0]}:{self._auth[1]}".encode()).decode()
            request.add_header("Authorization", f"Basic {token}")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as answer:
                raw = answer.read()
                if answer.status not in expect:
                    raise RuntimeError(f"CouchDB answered {answer.status}")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            if exc.code in expect:
                raw = exc.read()
                return json.loads(raw) if raw else {}
            raise
        except (urllib.error.URLError, OSError) as exc:
            raise RuntimeError(
                f"the CouchDB at {self.url} did not answer: {exc}. em-catalog "
                f"will not run with an index it cannot reach — the studies are "
                f"safe in the object store, but the catalogue would be blind"
            ) from None

    def _ensure_database(self) -> None:
        self._request("PUT", f"/{self.database}", expect=(201, 202, 412))
        for index in self._INDEXES:
            self._request("POST", f"/{self.database}/_index", index,
                          expect=(200, 201))

    def _doc(self, study_id: str) -> Optional[Dict[str, Any]]:
        try:
            return self._request("GET", f"/{self.database}/"
                                 f"{urllib.parse.quote(str(study_id), safe='')}")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise

    # ── the interface ────────────────────────────────────────────────────────

    def upsert(self, card: Dict[str, Any]) -> None:
        study_id = card.get("id")
        if not study_id:
            raise ValueError("a card without an id cannot be indexed")
        hc2, hc1 = _hdt_keys(card)
        # `type: "study"` is the spec's word (§7): the catalogue's documents sit
        # beside Heriverse's `scene` ones in the same database.
        document = {"_id": str(study_id), "type": "study", "card": card,
                    "title": card.get("title"), "haystack": _haystack(card),
                    "authors": _authors_blob(card), "license": card.get("license"),
                    "visibility": card.get("visibility"), "hc2": hc2, "hc1": hc1,
                    "checksum": card.get("checksum")}
        existing = self._doc(str(study_id))
        if existing and existing.get("_rev"):
            document["_rev"] = existing["_rev"]
        self._request("PUT", f"/{self.database}/"
                      f"{urllib.parse.quote(str(study_id), safe='')}", document)

    def get(self, study_id: str) -> Optional[Dict[str, Any]]:
        document = self._doc(study_id)
        return document.get("card") if document else None

    def search(self, **filters: Any) -> List[Dict[str, Any]]:
        selector: Dict[str, Any] = {"type": "study"}
        text = (filters.get("q") or "").strip().lower()
        if text:
            selector["haystack"] = {"$regex": f"(?i){urllib.parse.unquote(text)}"}
        for field in ("author", "orcid"):
            value = (filters.get(field) or "").strip().lower()
            if value:
                selector["authors"] = {"$regex": f"(?i){value}"}
        for field in ("license", "visibility", "hc2", "hc1"):
            value = (filters.get(field) or "").strip()
            if value:
                selector[field] = value
        answer = self._request("POST", f"/{self.database}/_find",
                               {"selector": selector, "limit": 10000})
        cards = [doc.get("card") for doc in answer.get("docs", [])
                 if doc.get("card")]
        cards.sort(key=lambda c: (c.get("title") is None, c.get("title") or "",
                                  c.get("id") or ""))
        return cards

    def list(self, view: str = "flat") -> Any:
        cards = self.search()
        return group_by_hdt(cards) if view == "hdt" else cards

    def remove(self, study_id: str) -> bool:
        document = self._doc(study_id)
        if not document or not document.get("_rev"):
            return False
        self._request("DELETE", f"/{self.database}/"
                      f"{urllib.parse.quote(str(study_id), safe='')}"
                      f"?rev={document['_rev']}")
        return True

    def reindex(self, cards: Any) -> int:
        rows = [c for c in cards if c.get("id")]
        keep = {str(c["id"]) for c in rows}
        for existing in self.search():
            if str(existing.get("id")) not in keep:
                self.remove(str(existing.get("id")))
        for card in rows:
            self.upsert(card)
        return len(rows)


# ── choosing one ─────────────────────────────────────────────────────────────

def index_from_env(environ: Optional[Dict[str, str]] = None) -> CatalogIndex:
    """CouchDB when configured, SQLite otherwise — and never a silent third thing.

    Half a CouchDB configuration is an error for the same reason half a MinIO one
    is: an operator who set `COUCHDB_URL` and mistyped the password must hear
    about it, rather than run a catalogue whose records are quietly in a file
    nobody backs up.
    """
    env = dict(environ if environ is not None else os.environ)
    url = (env.get("COUCHDB_URL") or env.get("EM_CATALOG_COUCHDB_URL") or "").strip()
    user = (env.get("COUCHDB_USER") or env.get("EM_CATALOG_COUCHDB_USER") or "").strip()
    password = (env.get("COUCHDB_PASSWORD")
                or env.get("EM_CATALOG_COUCHDB_PASSWORD") or "").strip()
    database = (env.get("COUCHDB_DATABASE")
                or env.get("EM_CATALOG_COUCHDB_DATABASE") or "em-catalog").strip()
    if url:
        if user and not password:
            raise RuntimeError(
                "the CouchDB index is half-configured: a user without a "
                "password. Refusing to start rather than falling back to the "
                "dev index — an operator who believes their records are in "
                "CouchDB must not find them in a local file.")
        return CouchDbCatalogIndex(url, database=database, user=user,
                                   password=password)
    path = (env.get("EM_CATALOG_DB") or ":memory:").strip()
    return SqliteCatalogIndex(path)


def describe(index: Any) -> str:
    """For `/health` — which index is actually answering."""
    if isinstance(index, CouchDbCatalogIndex):
        return f"couchdb ({index.url}/{index.database})"
    if isinstance(index, SqliteCatalogIndex):
        return f"sqlite ({index.path})"
    return type(index).__name__
