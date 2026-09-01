"""The link this catalogue WRITES, read by the parser that will receive it.

Three implementations of one grammar exist — `stratigraph-server/app/handoff.py`,
`EMStudio/frontend/src/handoff.ts`, and this module, which is the one that
*writes* it. A writer measured only against its own reader is a writer that can
be confidently wrong, and it was: from 29 August the catalogue emitted
`stratigraph://open?study=<id>` and every consumer refused it («the link names no
room»), in a log nobody was reading. The study button of the front door could not
work by construction.

So this file does the one thing the catalogue's own suite could not: it hands the
link to **StratiGraph Server's parser** and asserts it comes back as the study it
named. Skipped, loudly, when that repo is not beside this one — a check that
silently passes when it cannot run is worse than no check.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

from app.deeplink import SCHEME, open_targets

_SERVER = pathlib.Path(__file__).resolve().parents[2] / "stratigraph-server"


def _server_handoff():
    """StratiGraph Server's `app.handoff`, imported from the sibling checkout.

    By path rather than as a dependency: the two services are deployed
    separately and neither installs the other. What is being measured is
    precisely that two *independent* implementations agree.
    """
    if not (_SERVER / "app" / "handoff.py").exists():
        pytest.skip(f"stratigraph-server is not at {_SERVER}: the cross-service "
                    f"grammar check needs both checkouts side by side")
    # a stub package, so importing `app.handoff` from over there does not collide
    # with THIS service's `app`
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_server_handoff", _SERVER / "app" / "handoff.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("_server_handoff", module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def catalog_base(monkeypatch):
    monkeypatch.setenv("EM_CATALOG_PUBLIC_URL", "https://em.example.org")
    return "https://em.example.org"


def test_the_scheme_link_names_the_catalogue_and_not_only_the_study(catalog_base):
    """The whole bug, in one assertion: an id with no address is unresolvable."""
    doors = open_targets("study:abc", emjson_url=f"{catalog_base}/catalog/x")
    link = doors["apps"]["emstudio"]["scheme"]
    assert link.startswith(f"{SCHEME}://open?")
    assert "study=" in link
    assert "catalog=" in link


def test_the_link_we_write_is_read_by_the_SERVER_S_parser(catalog_base):
    """Measured between the services, not deduced from the comments."""
    handoff = _server_handoff()
    doors = open_targets("study:abc", emjson_url=f"{catalog_base}/catalog/x")
    parsed = handoff.parse(doors["apps"]["emstudio"]["scheme"])
    assert parsed == {"kind": "study", "catalog": catalog_base,
                      "study": "study:abc"}


def test_the_two_modules_agree_on_the_scheme():
    """One namespace. If these ever differ, every link in flight is dead."""
    handoff = _server_handoff()
    assert SCHEME == handoff.SCHEME


def test_the_link_carries_no_credential(catalog_base):
    """The property the parser enforces, asserted on the WRITING side too: a
    reader that refuses tokens and a writer that sends them would be a contract
    kept by one side only."""
    doors = open_targets("study:abc", emjson_url=f"{catalog_base}/catalog/x")
    link = doors["apps"]["emstudio"]["scheme"]
    for forbidden in ("token", "access_token", "password", "secret", "bearer"):
        assert forbidden not in link


def test_the_catalogue_base_is_configuration_and_not_a_caller_s_choice(monkeypatch):
    """`EM_CATALOG_PUBLIC_URL` wins over anything passed in.

    The rule the module docstring states for the app bases, applied to the one
    that was added tonight: a link a caller could aim is a redirector, and this
    one would send somebody's editor to fetch a "study" from an address a
    stranger chose.
    """
    monkeypatch.setenv("EM_CATALOG_PUBLIC_URL", "https://real.example.org")
    doors = open_targets("study:abc", emjson_url="https://real.example.org/x",
                         catalog_base="https://attacker.example.org")
    link = doors["apps"]["emstudio"]["scheme"]
    assert "real.example.org" in link
    assert "attacker" not in link


def test_with_no_base_anywhere_the_link_omits_the_half_it_cannot_fill(monkeypatch):
    """Honest degradation, the same as a missing app base: no `catalog=`, and
    `emjson` still works. A link with an empty parameter would look complete."""
    monkeypatch.delenv("EM_CATALOG_PUBLIC_URL", raising=False)
    doors = open_targets("study:abc", emjson_url="https://x/y")
    link = doors["apps"]["emstudio"]["scheme"]
    assert "catalog=" not in link
    assert doors["apps"]["emstudio"]["emjson"] == "https://x/y"
