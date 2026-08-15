# em-catalog — the StratiGraph Catalog, reference implementation.
#
# Almost stateless: the studies live in the object store and the index is
# derivable from them. The one writable path is the dev index (SQLite), and a
# deployment that points at CouchDB does not need even that.
#
#   docker build -t em-catalog .
#   docker run --rm -p 8010:8000 em-catalog
#
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# `[rdf]` is what makes /catalog/study/{id}/ttl a real endpoint instead of an
# honest 501. `[geo]` is deliberately NOT taken: this service never reprojects.
ARG S3DGRAPHY_SPEC="s3dgraphy[rdf]>=1.6.0.dev13"

WORKDIR /srv/em-catalog

COPY pyproject.toml README.md ./
# PyJWT and minio are here and not behind a build arg, for the reason em-server
# states: an image that cannot verify a token comes up open, and an image that
# cannot reach the object store keeps its studies in a process that dies.
RUN pip install --upgrade pip && \
    pip install "${S3DGRAPHY_SPEC}" "fastapi>=0.110" "uvicorn[standard]>=0.27" \
                "PyJWT[crypto]>=2.8" "minio>=7.2"

COPY app ./app

# Not root. /srv/em-catalog-data exists in the image so a named volume mounted
# there is not created root-owned — the same trap em-server documents, and the
# SQLite index is exactly the file that would fail to be written.
RUN useradd --create-home --shell /usr/sbin/nologin emcatalog && \
    mkdir -p /srv/em-catalog-data && \
    chown -R emcatalog:emcatalog /srv/em-catalog /srv/em-catalog-data
USER emcatalog

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
