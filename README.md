# em-catalog — the StratiGraph Catalog, **reference implementation**

> **This is not the production Catalog.** The Catalog of the GA (WP6, D6.1) —
> PID/DOI minting, FAIR publication, Data Space circulation, the browse UI, the
> institutional deployment — is **3DR's** to build on the shared infrastructure.
> This service exists so that the *contract* they build against is something
> that RUNS. It is deliberately thin, it runs in the dev-stack, and everything
> it demonstrates is meant to be reimplemented against WP6's CouchDB and MinIO
> without anybody having to ask us what a study is.
>
> Base: `StratiGraph_Catalog_SPEC_per_3DR.md` (CNR → 3DR). Division of labour,
> from §9 of that spec: **CNR provides the contract, 3DR builds and deploys.**

## The principle, and everything that follows from it

    A study IS an em.json container. The container is the truth.
    The index is a projection, and can be rebuilt from the containers.

Which is why:

* `POST /catalog/studies` writes the **container first** and derives the index
  second — the failure that can happen is the recoverable one (a study that
  exists and is unlisted), never the unrecoverable one (a catalogue advertising
  a study nobody can fetch);
* `POST /catalog/reindex` rebuilds the **whole** index by re-reading the object
  store. It is the architectural claim, executable: if it works, the index was
  never a second truth and can be swapped for another implementation with no
  migration;
* no field is ever written that a container does not already carry. The card is
  derived by **s3Dgraphy** (`api.study_metadata`) — a catalogue that parsed
  containers itself would be a second reader, and the day it disagreed with the
  library the index would become a second truth.

Metadata are **not reinvented**: authorship, licence and embargo already live as
graph-scope nodes (DP-65), the HDT pair is HDT-O's vocabulary (HC1/HC2), the
version is the container's own (P3). The catalogue *exposes and indexes* them.

## The two views (spec §4)

* **flat** — search and facets over the studies;
* **HDT** — the N studies of one heritage object over time. Sarmizegetusa in
  1978, in 2013, in 2026: three containers, one Heritage Digital Twin.

## The two formats are NOT interchangeable (spec §5)

| route | what it is | what it is for |
|---|---|---|
| `/catalog/study/{id}/emjson` | **the container** | the *usable* truth: it carries the per-field merge clocks, so a study fetched this way can be re-edited and merged |
| `/catalog/study/{id}/ttl` | the RDF projection, **publish mode** | publication, SPARQL, interop with the KG Engine |

The TTL is isomorphic on content but does **not** carry the field clocks, so a
study round-tripped through RDF comes home with node-level merge granularity.
The difference is silent until the day it costs somebody an afternoon. And
`publish` mode means tombstones do not travel: a deleted US must be **absent**
from a disseminated projection, not marked in it (`s3dgraphy.dissemination`).

## API

```
GET    /health                                  liveness, capabilities, which store/index
GET    /catalog/studies?q=&author=&orcid=&license=&hc2=&hc1=&view=flat|hdt
GET    /catalog/hdt/{hc2}                       one heritage object, its studies
GET    /catalog/study/{id}                      the card
GET    /catalog/study/{id}/emjson               the container
GET    /catalog/study/{id}/ttl                  the published projection
GET    /catalog/study/{id}/open?app=emstudio|blender|heriverse
POST   /catalog/studies?study_id=               register / replace          [token]
DELETE /catalog/study/{id}                      withdraw                    [token]
POST   /catalog/reindex                         rebuild from the containers [token]
```

**Visibility.** A study whose header says `visibility: public` is served without
a token — that is what publishing means. Everything else is 401 without and 200
with, and **restricted is the default**: the failure directions are not
symmetric. An anonymous catalogue listing shows the public studies rather than a
401 or an empty list, because discovery is the point and work in progress must
not leak while it happens.

**"Open in…"** returns a *descriptor*, not a redirect, and marks what is
proposed. The `emjson` URL works today in all three apps; the custom scheme
(`emstudio://open?study=…`) is spec §6's example and **no handler is registered
anywhere yet**, so it says so. A button that does nothing on every machine on
earth is worse than an absent one.

## Running it

```bash
python3 -m venv .venv && .venv/bin/pip install -e . -e ../s3Dgraphy
.venv/bin/uvicorn app.main:app --reload --port 8010
```

In the dev-stack (with MinIO, Keycloak and the rest):

```bash
cd ../em-server/dev-stack
docker-compose --env-file .env.dev -f docker-compose.dev.yml up -d em-catalog
python smoke_catalog.py
```

## Configuration

| variable | what it does |
|---|---|
| `MINIO_ENDPOINT` / `_ACCESS_KEY` / `_SECRET_KEY` / `_BUCKET` | the container store. **The same variables em-server reads** — one bucket, two prefixes. Half of them set is a startup refusal, never a fallback to memory |
| `EM_CATALOG_DB` | the dev index file (SQLite). Absent → `:memory:` |
| `COUCHDB_URL` / `_USER` / `_PASSWORD` / `_DATABASE` | the deploy index. Set → used; unset → SQLite. Never chosen silently |
| `OIDC_ISSUER` (or `TOKEN_ENDPOINT`), `OIDC_AUDIENCE` (or `CLIENT_ID_em`) | Keycloak. Half-configured → the process refuses to start |
| `EM_CATALOG_PUBLIC_URL` | the public base written into "open in" answers, when the proxy does not forward the host |
| `EM_CATALOG_EMSTUDIO_URL`, `EM_CATALOG_HERIVERSE_URL` | where those apps live, for the deep links |

## The seam for 3DR

`app/index.py` is the interface (`upsert / get / search / list / remove /
reindex`) with **two** implementations: SQLite for the dev machine and
**CouchDB** for the deployment, config-gated exactly like the object store. The
CouchDB documents carry `type: "study"` so they sit beside Heriverse's `scene`
documents in the same database (spec §7) — a new document type, not an inflation
of `sceneController`.

What 3DR reuses is the **card** (`s3dgraphy.api.study_metadata`) and this
**interface**, not our storage.

## Out of scope, and deliberately so

PID/DOI minting, FAIR publication, Data Space circulation, expert review, the
browse UI, the institutional deployment — 3DR / production. Also out: the
triplestore (the `/ttl` here is generated on demand via the round-trip; Virtuoso
is WP4/PSNC's), and image-level auth for restricted studies (a decision with its
own trigger).
