"""em-catalog — the StratiGraph Catalog, as a REFERENCE implementation.

**Read this first: what this service is and what it is not.**

It is the *contract made executable*. The Catalog of the GA (WP6, D6.1) —
PID/DOI minting, FAIR publication, Data Space circulation, the browse UI, the
institutional deployment — is **3DR's** to build on the shared infrastructure.
This service exists so that the contract they build against is something that
RUNS: register a study, search it, fetch it back, open it in an app. It is
deliberately thin, and everything it demonstrates is meant to be reimplemented
against WP6's CouchDB and MinIO without asking us what a study is.

**The one principle, from which everything else follows.**

    A study IS an em.json container. The container is the truth.
    The index is a projection, and can be rebuilt from the containers.

That is why `POST /catalog/studies` stores the container first and indexes
second; why `reindex` re-reads the object store rather than a journal; and why
nothing in this service ever writes a metadata field that a container does not
already carry. The card is derived by **s3Dgraphy** (`api.study_metadata`) — a
catalogue that parsed containers itself would become a second reader, and the
day it disagreed with the library, the index would be a second truth.

**The rules inherited from em-server**, because a sibling service that broke them
would teach the wrong thing:

* the domain lives in s3Dgraphy; this is orchestration, an index, and HTTP;
* everything under `/catalog`, so the path is a promise 3DR can hold us to;
* `/health` unversioned as well, because a probe belongs to the infrastructure;
* the durable truth is not on this process's disk (the object store holds it);
* **visibility defaults to restricted** — the failure directions are not
  symmetric: a public study behind a token annoys somebody, an in-progress study
  served openly publishes an interpretation nobody has finished making.

**Two views** (spec §4): the flat catalogue of studies, and the HDT view that
groups the N studies of one heritage object over time — Sarmizegetusa in 1978, in
2013, in 2026, each one a container.

**Retrieval, and why the two formats are not interchangeable** (spec §5): the
em.json is the *usable* truth — it carries the per-field merge clocks, so a study
fetched this way can be re-edited and merged. The TTL is a projection for
publication and SPARQL: isomorphic on content, but it does **not** carry the
field clocks, so a study round-tripped through RDF comes back with node-level
merge granularity. `/emjson` is what you re-open; `/ttl` is what you publish. And
`/ttl` is served in **publish mode**, so tombstones do not travel into a
disseminated projection (`s3dgraphy.dissemination`).
"""

from __future__ import annotations

import os
import uuid
from typing import Any, Dict, List, Optional

from fastapi import (APIRouter, Body, FastAPI, HTTPException, Query, Request,
                     Response)
from pydantic import BaseModel, Field

from .auth import AuthDependency, authenticator
from .deeplink import APPS, open_targets
from .deeplink import describe as deeplink_describe
from .index import describe as index_describe
from .index import group_by_hdt, index_from_env
from .store import describe as store_describe
from .store import store_from_env

try:  # the whole point of the service; a clear failure beats a mysterious one
    from s3dgraphy import api as em
except ImportError as exc:  # pragma: no cover — deployment error, not runtime
    raise RuntimeError(
        "em-catalog needs s3dgraphy importable: pip install s3dgraphy "
        f"(or -e ../s3Dgraphy). {exc}"
    ) from exc

__version__ = "0.1.0.dev0"

app = FastAPI(
    title="em-catalog",
    version=__version__,
    summary="The StratiGraph Catalog — reference implementation. Studies are "
            "em.json containers; the index is derived.",
    description=__doc__,
)

#: Built at import, so a misconfiguration fails at STARTUP — when an operator is
#: watching — rather than on the first request, when nobody is.
STORE = store_from_env()
INDEX = index_from_env()

#: Everything that WRITES, or that reads something not published, sits here.
catalog = APIRouter(prefix="/catalog", dependencies=[AuthDependency])

#: …and everything whose access is decided by the STUDY rather than by the route
#: sits here, doing the check itself. A router-level dependency would refuse a
#: public study before the handler could look at it — the same arrangement
#: em-server uses for a public IIIF manifest, and for the same reason.
catalog_public = APIRouter(prefix="/catalog")

public = APIRouter()


# ── health ────────────────────────────────────────────────────────────────────

class Health(BaseModel):
    ok: bool = True
    service: str = "em-catalog"
    version: str
    s3dgraphy: Optional[str] = None
    #: what this build can actually do — a client reading this does not have to
    #: discover a 501 by trying
    capabilities: Dict[str, bool] = Field(default_factory=dict)
    auth: str = "dev-no-auth"
    #: WHERE THE TRUTH IS. An operator who reads "memory" knows their studies die
    #: with the process, instead of finding out.
    container_store: str = "memory"
    #: …and which index is answering. It is derivable, so this is a performance
    #: and operations fact rather than a safety one — but it is still a fact.
    index: str = "sqlite"
    studies: int = 0
    #: which apps this deployment can offer "open in" for
    open_in: Dict[str, Optional[str]] = Field(default_factory=dict)


def _health() -> Health:
    def importable(module: str) -> bool:
        import importlib.util
        return importlib.util.find_spec(module) is not None

    version = None
    try:
        import s3dgraphy
        version = getattr(s3dgraphy, "__version__", None)
    except Exception:  # pragma: no cover
        pass
    try:
        count = len(INDEX.search())
    except Exception:  # pragma: no cover — an index that cannot count still lives
        count = 0
    return Health(
        version=__version__,
        s3dgraphy=version,
        capabilities={
            "study_metadata": hasattr(em, "study_metadata"),
            "export_ttl": importable("rdflib"),
            # the publish mode is what keeps a deleted US out of a published
            # projection; a build without it must SAY so rather than serve a
            # /ttl that quietly carries tombstones
            "ttl_publish_mode": importable("s3dgraphy.dissemination"),
            "hdt_view": True,
        },
        auth=authenticator.settings.describe(),
        container_store=store_describe(STORE),
        index=index_describe(INDEX),
        studies=count,
        open_in=deeplink_describe(),
    )


@public.get("/health", response_model=Health, tags=["meta"])
def health_unversioned() -> Health:
    """The orchestrator's probe. Same answer as `/catalog/health`."""
    return _health()


@catalog_public.get("/health", response_model=Health, tags=["meta"])
def health() -> Health:
    return _health()


# ── helpers ───────────────────────────────────────────────────────────────────

def _mint_study_id() -> str:
    """`study:<uuid>` — the spec's shape (§2.2).

    The catalogue mints it, not the library: an identity is a decision about the
    world, and s3Dgraphy deliberately refuses to invent one (`study_metadata`
    returns `id: None` when nobody has said).
    """
    return f"study:{uuid.uuid4()}"


def _card_of(doc: Dict[str, Any], study_id: str) -> Dict[str, Any]:
    """The card, derived by the LIBRARY. One reader of containers, not two."""
    try:
        return em.study_metadata(doc, study_id=study_id)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"not a readable em.json container: {exc}") from None


def _container_url(request: Request, study_id: str) -> str:
    """The PUBLIC url of the container — the form the reader can fetch.

    Built from the request, so a deployment behind Caddy answers with the address
    the caller actually used. `EM_CATALOG_PUBLIC_URL` overrides it for the case
    the proxy does not forward the host — configuration, never a query
    parameter: an "open in" answer that a caller could point anywhere is a
    redirector, not a catalogue.
    """
    configured = (os.environ.get("EM_CATALOG_PUBLIC_URL") or "").strip()
    base = configured.rstrip("/") if configured else str(request.base_url).rstrip("/")
    return f"{base}/catalog/study/{study_id}/emjson"


def _require_visible(card: Dict[str, Any], request: Request,
                     token: Optional[str] = None) -> None:
    """A public study is served to anybody; anything else needs a token.

    Same rule as an em-server room, and the same reasoning: `public` is the
    dissemination tier — validated work, meant to be read — and everything else
    is in progress. `?token=` is accepted beside the header because a viewer
    (Mirador, a browser opening a link) cannot set one.
    """
    if card.get("visibility") == "public":
        return
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer ") or not token:
        authenticator.require_token(request)
        return
    if not authenticator.settings.enforcing:
        return
    authenticator.verify(token.strip())


def _load_or_404(study_id: str) -> Dict[str, Any]:
    doc = STORE.get(study_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"no study {study_id!r}")
    return doc


def _card_or_404(study_id: str) -> Dict[str, Any]:
    """The card from the INDEX when it is there, from the CONTAINER when it is
    not — because the container is the truth and a gap in a projection must not
    look like a missing study."""
    card = INDEX.get(study_id)
    if card is not None:
        return card
    doc = STORE.get(study_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"no study {study_id!r}")
    return _card_of(doc, study_id)


# ── register / publish a study ────────────────────────────────────────────────

class Registered(BaseModel):
    id: str
    created: bool
    card: Dict[str, Any]
    #: where the container went — the storage key, for an operator
    container_ref: str
    #: the STORAGE digest of the bytes as written (the card carries the CONTENT
    #: digest, which ignores layout and version: two questions, two answers)
    sha256: str


@catalog.post("/studies", response_model=Registered, tags=["studies"],
              status_code=201)
def register_study(doc: Dict[str, Any] = Body(..., description="an em.json container"),
                   study_id: Optional[str] = Query(
                       default=None,
                       description="update an existing study instead of minting one")
                   ) -> Registered:
    """Register (or replace) a study: **the container goes to the store, then the
    index is derived from it.**

    That order is the whole design. If the process died between the two, the
    study would exist and be unlisted — recoverable by `reindex`. The other
    order would leave the catalogue advertising a study nobody can fetch, which
    no rebuild can repair.

    `visibility` is **not** a parameter: it is read from the container's header,
    where its author put it. A study's openness is a property of the study, and
    an endpoint that let a caller pass it would let a caller publish somebody
    else's work in progress.
    """
    identity = (study_id or "").strip() or _mint_study_id()
    card = _card_of(doc, identity)
    written = STORE.put(identity, doc)
    INDEX.upsert(card)
    return Registered(id=identity, created=bool(written.get("created", True)),
                      card=card, container_ref=str(written.get("key") or ""),
                      sha256=str(written.get("sha256") or ""))


@catalog.delete("/study/{study_id}", tags=["studies"])
def remove_study(study_id: str) -> Dict[str, Any]:
    """Remove a study from the catalogue: the container AND its card.

    Not a tombstone. A catalogue entry is a *statement that a study is
    published*; withdrawing it is withdrawing the statement, and the merge
    machinery that needs tombstones lives in the containers, not here.
    """
    removed_index = INDEX.remove(study_id)
    removed_store = STORE.remove(study_id)
    if not (removed_index or removed_store):
        raise HTTPException(status_code=404, detail=f"no study {study_id!r}")
    return {"ok": True, "id": study_id, "removed": {
        "container": removed_store, "index": removed_index}}


# ── search / list ─────────────────────────────────────────────────────────────

@catalog_public.get("/studies", tags=["studies"])
def list_studies(request: Request,
                 q: Optional[str] = Query(default=None, description="free text"),
                 author: Optional[str] = Query(default=None),
                 orcid: Optional[str] = Query(default=None),
                 license: Optional[str] = Query(default=None),
                 hc2: Optional[str] = Query(default=None,
                                            description="Heritage Digital Twin"),
                 hc1: Optional[str] = Query(default=None,
                                            description="Heritage Entity"),
                 view: str = Query(default="flat", pattern="^(flat|hdt)$"),
                 token: Optional[str] = Query(default=None)) -> Dict[str, Any]:
    """The catalogue: search, filter, and the two views.

    **What an anonymous caller sees is the PUBLIC studies.** Not an empty list
    and not a 401: a catalogue whose whole purpose is discovery must answer
    somebody who has not logged in, and it must not leak the existence of work in
    progress while doing it. With a token, the caller sees everything.

    This is the one place where the filter is applied *after* the query rather
    than as another `WHERE`: the visibility of a card is a fact of the card, and
    keeping the rule in ONE readable line here beats spreading it through two
    index implementations.
    """
    authenticated = _is_authenticated(request, token)
    cards = INDEX.search(q=q, author=author, orcid=orcid, license=license,
                         hc2=hc2, hc1=hc1)
    if not authenticated:
        cards = [c for c in cards if c.get("visibility") == "public"]
    if view == "hdt":
        return {"view": "hdt", "count": len(cards), "groups": group_by_hdt(cards)}
    return {"view": "flat", "count": len(cards), "studies": cards}


def _is_authenticated(request: Request, token: Optional[str]) -> bool:
    """Did the caller present something valid? A question, not a gate.

    In dev mode (no OIDC configured) everybody is authenticated, which is what
    "dev mode" means and what `/health` reports in a word.
    """
    if not authenticator.settings.enforcing:
        return True
    header = request.headers.get("authorization") or ""
    try:
        if header.lower().startswith("bearer "):
            authenticator.require_token(request)
            return True
        if token:
            authenticator.verify(token.strip())
            return True
    except HTTPException:
        # A BAD token is not an error here: this route answers anonymously by
        # design, so the caller simply gets the public catalogue. Raising would
        # turn an expired session into "the catalogue is down".
        return False
    return False


@catalog_public.get("/hdt/{hc2:path}", tags=["views"])
def hdt_view(hc2: str, request: Request,
             token: Optional[str] = Query(default=None)) -> Dict[str, Any]:
    """One heritage object, its studies over time (spec §4).

    The path is `:path` because an HC2 key is often an IRI, and an IRI has
    slashes in it. Refusing those would mean the view only worked for the studies
    whose twin happened to be identified by a bare id.
    """
    authenticated = _is_authenticated(request, token)
    cards = INDEX.search(hc2=hc2)
    if not authenticated:
        cards = [c for c in cards if c.get("visibility") == "public"]
    if not cards:
        raise HTTPException(status_code=404,
                            detail=f"no studies for the digital twin {hc2!r}")
    groups = group_by_hdt(cards)
    return {"hc2": hc2, "count": len(cards),
            "hc1": groups[0].get("hc1") if groups else None,
            "studies": cards}


# ── one study ─────────────────────────────────────────────────────────────────

@catalog_public.get("/study/{study_id}", tags=["studies"])
def get_study(study_id: str, request: Request,
              token: Optional[str] = Query(default=None)) -> Dict[str, Any]:
    """The study's card."""
    card = _card_or_404(study_id)
    _require_visible(card, request, token)
    return card


@catalog_public.get("/study/{study_id}/emjson", tags=["retrieval"])
def get_study_emjson(study_id: str, request: Request,
                     token: Optional[str] = Query(default=None)) -> Response:
    """**The container** — the usable truth (spec §5).

    This, and not the TTL, is what you re-open and re-edit: the container carries
    the per-field merge clocks, so two people who edited different fields of the
    same node still both keep their edit. A study fetched as RDF and converted
    back would come home with node-level granularity, and the difference is
    silent until the day it costs somebody an afternoon's work.
    """
    import json

    card = _card_or_404(study_id)
    _require_visible(card, request, token)
    doc = _load_or_404(study_id)
    return Response(
        content=json.dumps(doc, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition":
                 f'attachment; filename="{study_id.replace(":", "_")}.em.json"'})


@catalog_public.get("/study/{study_id}/ttl", tags=["retrieval"],
                    responses={200: {"content": {"text/turtle": {}}}})
def get_study_ttl(study_id: str, request: Request,
                  token: Optional[str] = Query(default=None)) -> Response:
    """The study projected to Turtle, in **publish mode**.

    Publish mode is not a detail: a dissemination surface must not carry
    tombstones (`s3dgraphy.dissemination`), or a US somebody deleted would come
    back to life in whatever consumes these triples. Round-trip mode keeps them
    and lives in the library for the callers that need isomorphism; a catalogue
    is not one of them.

    501 without rdflib — the request was fine, this build simply cannot.
    """
    card = _card_or_404(study_id)
    _require_visible(card, request, token)
    doc = _load_or_404(study_id)

    graphs = doc.get("graphs") or {}
    header = doc.get("header") or {}
    graph_id = doc.get("active_graph_id") or next(iter(graphs), None)
    if not graph_id:
        raise HTTPException(status_code=404,
                            detail=f"study {study_id!r} holds no graph")
    graph, _warnings = em.load_emjson({"header": header,
                                       "graph": graphs[graph_id]})
    try:
        ttl = em.project_ttl(graph, mode="publish")
    except TypeError:
        # a s3dgraphy older than the publish mode: refuse rather than serve a
        # projection that may carry deletions into a published graph
        raise HTTPException(
            status_code=501,
            detail="this build's s3dgraphy has no RDF publish mode, and serving "
                   "a round-trip projection here would publish tombstones"
        ) from None
    except em.MissingDependency as exc:
        raise HTTPException(
            status_code=501,
            detail=f"TTL projection unavailable — this build has no rdflib ({exc})"
        ) from None
    except Exception as exc:
        raise HTTPException(status_code=500,
                            detail=f"TTL projection failed: {exc}") from None
    return Response(
        content=ttl, media_type="text/turtle",
        headers={"Content-Disposition":
                 f'attachment; filename="{study_id.replace(":", "_")}.ttl"'})


@catalog_public.get("/study/{study_id}/open", tags=["retrieval"])
def open_study(study_id: str, request: Request,
               app: Optional[str] = Query(
                   default=None, description=f"one of {', '.join(APPS)}; "
                                             f"all of them when omitted"),
               token: Optional[str] = Query(default=None)) -> Dict[str, Any]:
    """“Open in…” (spec §6): the same container, in whichever app.

    What comes back is a descriptor, not a redirect: the caller is a UI that has
    to decide between a scheme it may not have a handler for and a URL it can
    always fetch, and a 302 would take that decision away and get it wrong.
    """
    card = _card_or_404(study_id)
    _require_visible(card, request, token)
    apps = [app] if app else None
    try:
        return open_targets(study_id, emjson_url=_container_url(request, study_id),
                            apps=apps)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


# ── the index is derived, and here is the proof ───────────────────────────────

class Reindexed(BaseModel):
    ok: bool = True
    studies: int
    #: studies whose container is in the store but could not be read into a card
    #: — named, never silently skipped
    unreadable: List[str] = Field(default_factory=list)


@catalog.post("/reindex", response_model=Reindexed, tags=["admin"])
def reindex() -> Reindexed:
    """Rebuild the WHOLE index by re-reading the containers in the object store.

    This endpoint is the architectural claim, executable. If it works, the index
    was never a second truth: it can be dropped, corrupted, or replaced by
    another implementation, and the catalogue comes back from the studies.

    A container the library cannot read is REPORTED, not skipped: an index that
    silently lost a study during a rebuild is exactly the failure a rebuild is
    supposed to repair.
    """
    cards: List[Dict[str, Any]] = []
    unreadable: List[str] = []
    for study_id in STORE.list():
        doc = STORE.get(study_id)
        if doc is None:
            unreadable.append(study_id)
            continue
        try:
            cards.append(em.study_metadata(doc, study_id=study_id))
        except Exception:
            unreadable.append(study_id)
    count = INDEX.reindex(cards)
    return Reindexed(studies=count, unreadable=unreadable)


app.include_router(public)
app.include_router(catalog_public)
app.include_router(catalog)
