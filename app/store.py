"""Where the studies actually live — and the reason the index can be thrown away.

**A study is one em.json container, and the container is the TRUTH.** Everything
else this service holds is a projection of it: the index (`index.py`) is derived,
the TTL is generated on demand, the cards are read at write time. That is not
tidiness, it is the property that keeps a catalogue honest — if the index and the
containers ever disagree, the containers win and `reindex` proves it by rebuilding
the index from them.

Same shape as em-server's `assets.py`, and deliberately so: an interface of four
methods, an in-memory implementation that says it is for tests, and MinIO as the
deployment target — a line of configuration, not a rewrite.

**Not content-addressed, and this is the one real difference from an asset.** An
asset is immutable bytes and its name IS its digest; a *study* evolves under a
stable identity — that is what makes "the 1978 study and the 2026 study of the
same monument" a sentence the HDT view can say. So the key is the study's id, and
the digest travels in the metadata as the answer to "is the copy you have still
the copy I indexed" rather than as the name. Immutable citation is a different
job, done by pinning a version (`container.pin_version`), and pinning is
deliberately not the same act as saving.

The bucket is the one em-server already writes assets into; studies live under
their own **prefix** (spec §7: same store, shared prefixes). A catalogue that
demanded a bucket of its own would be one more thing to provision for no gain.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from typing import Any, Dict, Iterable, List, Optional, Protocol

#: Where study containers sit inside the shared bucket.
STUDY_PREFIX = "studies/"
#: The suffix, so a human browsing the bucket can see what these objects are.
STUDY_SUFFIX = ".em.json"

MEDIA_TYPE = "application/json"


def container_bytes(doc: Dict[str, Any]) -> bytes:
    """The canonical bytes of a container.

    Sorted keys, no ASCII escaping: the same document must serialise the same way
    every time, or the stored digest would depend on who wrote it. (This is the
    STORAGE digest — bytes on the wire. The study's CONTENT digest, which ignores
    layout and version, is s3Dgraphy's `content_digest` and is a different
    question with a different answer.)
    """
    return json.dumps(doc, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def bytes_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def object_key(study_id: str) -> str:
    """`study:abc-123` → `studies/study_abc-123.em.json`.

    The colon is legal in an S3 key and illegal in half the tools people use to
    look at one, so it is replaced. The mapping is total and reversible enough
    for listing, which is all `reindex` needs.
    """
    safe = str(study_id).replace(":", "_").replace("/", "_")
    return f"{STUDY_PREFIX}{safe}{STUDY_SUFFIX}"


def study_id_from_key(key: str) -> str:
    """The inverse, for `list()` — a catalogue rebuilding itself from the bucket
    must be able to name what it found."""
    name = key[len(STUDY_PREFIX):] if key.startswith(STUDY_PREFIX) else key
    if name.endswith(STUDY_SUFFIX):
        name = name[: -len(STUDY_SUFFIX)]
    return name.replace("_", ":", 1) if name.startswith("study_") else name


class ContainerStore(Protocol):
    """Put a study, get a study, list them, remove one. Nothing else lives here."""

    def put(self, study_id: str, doc: Dict[str, Any]) -> Dict[str, Any]:
        """Store the container; return `{key, sha256, size, created}`."""

    def get(self, study_id: str) -> Optional[Dict[str, Any]]:
        """The container, or None."""

    def list(self) -> List[str]:
        """Every study id in the store — the input to a rebuild."""

    def remove(self, study_id: str) -> bool:
        """True when something was there to remove."""


class InMemoryContainerStore:
    """For tests and a laptop run — and it says so.

    Not the deployment target: it dies with the process, which is the property
    the MinIO implementation exists to remove. A catalogue whose truth lives here
    has no truth.
    """

    def __init__(self) -> None:
        self._blobs: Dict[str, bytes] = {}
        self._lock = threading.Lock()

    def put(self, study_id: str, doc: Dict[str, Any]) -> Dict[str, Any]:
        data = container_bytes(doc)
        key = object_key(study_id)
        with self._lock:
            created = key not in self._blobs
            self._blobs[key] = data
        return {"key": key, "sha256": bytes_digest(data), "size": len(data),
                "created": created}

    def get(self, study_id: str) -> Optional[Dict[str, Any]]:
        data = self._blobs.get(object_key(study_id))
        return json.loads(data.decode("utf-8")) if data is not None else None

    def list(self) -> List[str]:
        return sorted(study_id_from_key(k) for k in self._blobs)

    def remove(self, study_id: str) -> bool:
        with self._lock:
            return self._blobs.pop(object_key(study_id), None) is not None


class MinioContainerStore:
    """The deployment target: the studies live in the object store.

    The `minio` client is a hard dependency of this service (see pyproject), so a
    missing one is a broken build rather than a configuration choice — but the
    construction still fails **here**, with a sentence, rather than at the first
    upload with a stack trace from inside a request.
    """

    def __init__(self, endpoint: str, access_key: str, secret_key: str,
                 bucket: str, secure: bool = True) -> None:
        try:
            from minio import Minio  # type: ignore
        except ImportError as exc:  # pragma: no cover — depends on the build
            raise RuntimeError(
                "the MinIO container store needs the `minio` client, which this "
                "build does not have: pip install minio") from exc

        self.bucket = bucket
        self.endpoint = endpoint
        # host:port WITHOUT a scheme, the scheme as a flag — passing the URL
        # whole is the first thing that goes wrong here
        host = endpoint.split("://", 1)[-1].rstrip("/")
        self._client = Minio(host, access_key=access_key, secret_key=secret_key,
                             secure=secure)
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        from minio.error import S3Error  # type: ignore

        try:
            if not self._client.bucket_exists(self.bucket):
                self._client.make_bucket(self.bucket)
        except S3Error as exc:
            raise RuntimeError(
                f"the bucket '{self.bucket}' is not usable at {self.endpoint}: "
                f"{exc.code}. Either it does not exist and these credentials may "
                f"not create it, or they may not read it") from exc
        except Exception as exc:      # network, DNS, TLS: not an S3 answer at all
            raise RuntimeError(
                f"the object store at {self.endpoint} did not answer: {exc}. "
                f"em-catalog will not start without the store that holds its "
                f"truth") from exc

    def put(self, study_id: str, doc: Dict[str, Any]) -> Dict[str, Any]:
        import io

        from minio.error import S3Error  # type: ignore

        data = container_bytes(doc)
        key = object_key(study_id)
        created = True
        try:
            self._client.stat_object(self.bucket, key)
            created = False
        except S3Error as exc:
            if exc.code not in ("NoSuchKey", "NoSuchObject", "NotFound"):
                raise
        self._client.put_object(self.bucket, key, io.BytesIO(data), len(data),
                                content_type=MEDIA_TYPE)
        return {"key": key, "sha256": bytes_digest(data), "size": len(data),
                "created": created}

    def get(self, study_id: str) -> Optional[Dict[str, Any]]:
        from minio.error import S3Error  # type: ignore

        response = None
        try:
            response = self._client.get_object(self.bucket, object_key(study_id))
            return json.loads(response.read().decode("utf-8"))
        except S3Error as exc:
            if exc.code in ("NoSuchKey", "NoSuchObject", "NotFound"):
                return None
            raise
        finally:
            if response is not None:
                response.close()
                response.release_conn()

    def list(self) -> List[str]:
        found: Iterable[Any] = self._client.list_objects(
            self.bucket, prefix=STUDY_PREFIX, recursive=True)
        return sorted(study_id_from_key(obj.object_name) for obj in found
                      if obj.object_name.endswith(STUDY_SUFFIX))

    def remove(self, study_id: str) -> bool:
        from minio.error import S3Error  # type: ignore

        key = object_key(study_id)
        try:
            self._client.stat_object(self.bucket, key)
        except S3Error as exc:
            if exc.code in ("NoSuchKey", "NoSuchObject", "NotFound"):
                return False
            raise
        self._client.remove_object(self.bucket, key)
        return True


#: The same two spellings em-server reads, in the same order — one setting with
#: two names and a precedence, never two settings that will one day disagree.
#: Reading the SAME variables is what makes "the catalogue and the rooms share a
#: bucket" true in configuration and not only in prose.
_MINIO_KEYS = {
    "endpoint": ("MINIO_ENDPOINT", "EM_ASSET_S3_ENDPOINT"),
    "access_key": ("MINIO_ACCESS_KEY", "EM_ASSET_S3_ACCESS_KEY"),
    "secret_key": ("MINIO_SECRET_KEY", "EM_ASSET_S3_SECRET_KEY"),
    "bucket": ("MINIO_BUCKET", "EM_ASSET_S3_BUCKET"),
}


def _minio_settings(env: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """The MinIO configuration, or None when there is none at all.

    Half of it is an error, not a fallback: a deployment that named an endpoint
    and forgot the bucket must hear about it, because the alternative is a
    catalogue that came up storing its studies in RAM.
    """
    found: Dict[str, Any] = {}
    for field, names in _MINIO_KEYS.items():
        for name in names:
            value = (env.get(name) or "").strip()
            if value:
                found[field] = value
                break
    if not found:
        return None
    missing = [f for f in _MINIO_KEYS if f not in found]
    if missing:
        raise RuntimeError(
            f"the object store is half-configured: missing {', '.join(missing)}. "
            f"Refusing to fall back to memory — a catalogue whose studies "
            f"disappear with the process is worse than one that will not boot.")
    found["secure"] = not found["endpoint"].startswith("http://")
    return found


def store_from_env(environ: Optional[Dict[str, str]] = None) -> ContainerStore:
    """MinIO when configured; memory otherwise, loudly."""
    env = environ if environ is not None else os.environ
    settings = _minio_settings(dict(env))
    if settings:
        return MinioContainerStore(**settings)
    return InMemoryContainerStore()


def describe(store: Any) -> str:
    """For `/health`. An operator who reads "memory" knows their studies die with
    the process, instead of finding out."""
    if isinstance(store, MinioContainerStore):
        return f"minio ({store.endpoint}, bucket {store.bucket}, prefix {STUDY_PREFIX})"
    return "memory"
