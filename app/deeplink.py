"""“Open in…” — the action that closes the architecture, and what it can honestly promise today.

Spec §6: every study has a URI that resolves to its container, and the catalogue
offers to open it in EMStudio, in Blender/EMtools, or in Heriverse. The three
apps open **the same em.json container**, which is possible *precisely* because a
study is one portable datum — and once open, ADR-002 keeps them in step.

So the resolution has one non-negotiable part and one proposed part, and this
module keeps them visibly apart instead of blurring them into a plausible URL.

**What is real today** — `emjson`: the URL of the container itself. Every one of
the three apps can already consume it (EMStudio opens it, EMtools imports it,
Heriverse reads the container shape). Any client that does nothing else with this
answer can still act on that one field, which is the definition of a useful
contract.

**The scheme is now the ECOSYSTEM's** — `stratigraph://open?study=…`
(2026-08-29). It used to be `emstudio://`, which was a scheme owned by one
consumer: the opposite of what a handoff contract is for. StratiGraph Server
defines the same scheme for a ROOM (`stratigraph-server/app/handoff.py`), and the
two are deliberately one namespace with two entry points — the Catalog opens a
STUDY (resolve the container, and in time its room), the room browser opens a
ROOM. A consumer registers one handler and reads the action.

**It is still marked `proposed`, and honestly so.** The handler is registered in
EMStudio's desktop bundle and nowhere else: not on the web build, not in EMtools,
not on a machine that has only a browser. So the `web` URL stays beside it and
`proposed` says which half is aspiration — a catalogue that shipped an
unregistered scheme as if it were live would produce a button that does nothing,
and the failure would look like the user's fault. The day a consumer registers
it, its name comes out of `SCHEME_REGISTERED_IN` below and the note gets shorter.

The app bases are **configuration**, never a request parameter: where EMStudio
lives is a property of the deployment, and letting a caller name it would make
this endpoint a redirector to anywhere (the same rule `docs/URL-TOPOLOGY.md` in
StratiGraph Server states for internal fetches, applied to what we write into an answer).
"""

from __future__ import annotations

import os
import urllib.parse
from typing import Any, Dict, List, Optional

#: The apps a study can be opened in. Three, because those are the three that
#: read the container; a fourth arrives with its reader, not with a URL.
APPS = ("emstudio", "blender", "heriverse")

#: The ECOSYSTEM's scheme, not any one app's. Kept in step with
#: `stratigraph-server/app/handoff.py::SCHEME` — one namespace, two entry points
#: (a study here, a room there).
SCHEME = "stratigraph"

#: Where the handler actually EXISTS today. The list is the honest half of the
#: `proposed` flag: a button is live for the apps in here and a coin-toss
#: everywhere else, and saying which is the difference between a promise and a
#: measurement.
SCHEME_REGISTERED_IN = ("emstudio-desktop",)


def _base(*names: str, default: str = "") -> str:
    for name in names:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value.rstrip("/")
    return default


def open_targets(study_id: str, *, emjson_url: str,
                 apps: Optional[List[str]] = None) -> Dict[str, Any]:
    """How to open this study, per app.

    `emjson_url` is the PUBLIC url of the container — the caller builds it,
    because only the caller knows how it is being reached (the same
    internal/public split StratiGraph Server writes down: a document carries the form the
    *reader* can fetch).
    """
    wanted = [a for a in (apps or APPS) if a in APPS]
    if not wanted:
        raise ValueError(f"unknown app; the catalogue can open a study in "
                         f"{', '.join(APPS)}")

    quoted = urllib.parse.quote(str(study_id), safe="")
    targets: Dict[str, Any] = {}

    for app in wanted:
        if app == "emstudio":
            web = _base("EM_CATALOG_EMSTUDIO_URL")
            targets[app] = {
                # works today: EMStudio opens a container it is handed
                "emjson": emjson_url,
                "web": (f"{web}/?study={quoted}&emjson="
                        f"{urllib.parse.quote(emjson_url, safe='')}"
                        if web else None),
                # the ecosystem's scheme (§6, and `handoff.py` in the server):
                # registered in EMStudio's desktop bundle, nowhere else yet
                "scheme": f"{SCHEME}://open?study={quoted}",
                "proposed": ["scheme"],
                "registered_in": list(SCHEME_REGISTERED_IN),
                "note": "the custom scheme opens in EMStudio's DESKTOP build, "
                        "where the handler is registered; everywhere else use "
                        "`emjson` (or `web`, when the deployment names an "
                        "EMStudio). Same scheme as a room handoff — one "
                        "namespace, two actions.",
            }
        elif app == "blender":
            # EMtools has no HTTP endpoint that accepts a pushed container: it
            # JOINS a room, and it IMPORTS a file. So what the catalogue can
            # honestly hand it is the container URL.
            targets[app] = {
                "emjson": emjson_url,
                "how": "import the container in EMtools (Import → em.json), or "
                       "join the study's room to co-edit it",
                "proposed": ["push"],
                "note": "pushing a container into a running Blender would need "
                        "an em-bridge endpoint that does not exist today "
                        "(spec §6 describes it as the target arrangement).",
            }
        elif app == "heriverse":
            base = _base("EM_CATALOG_HERIVERSE_URL")
            targets[app] = {
                "emjson": emjson_url,
                "web": (f"{base}/?study={quoted}" if base else None),
                "proposed": [] if base else ["web"],
                "note": "Heriverse reads the container shape directly; the scene "
                        "is the study's published 3D dress.",
            }
    return {"study": study_id, "emjson": emjson_url, "apps": targets}


def describe() -> Dict[str, Optional[str]]:
    """Which app bases this deployment actually knows — for `/health`, so an
    operator can see why a button is missing before a user reports it."""
    return {
        "emstudio": _base("EM_CATALOG_EMSTUDIO_URL") or None,
        "heriverse": _base("EM_CATALOG_HERIVERSE_URL") or None,
    }
