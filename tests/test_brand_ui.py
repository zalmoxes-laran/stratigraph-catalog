"""The catalogue's own two views, and what keeps their identity honest.

The same three claims the other StratiGraph faces make (field assistant, room
browser, node console) — same brand, same reasoning:

* nothing is fetched at runtime: the theme, the faces and the marks are VENDORED
  (`sync-brand.sh`) and served same-origin;
* the stylesheet uses ROLES, not hexes;
* no text on a pure accent — the theme ships the inks that can carry text.

The READER this service also mounts is NOT covered: it is EMStudio's built
artefact, an Extended Matrix tool, and it keeps the EM look.
"""

from __future__ import annotations

import pathlib
import re

APP = pathlib.Path(__file__).resolve().parent.parent / "app"
BRAND = APP / "brand"
PAGE = APP / "ui" / "index.html"
SHEET = APP / "ui" / "catalog.css"

GUIDEBOOK = {"#F1EBE3", "#D9D1CF", "#383838", "#2E2D2C", "#C4B282", "#8A8021",
             "#A64724", "#E85B1A", "#CAD531", "#4AA7D9", "#1E275C"}
PURE_ACCENTS = ("--sg-info", "--sg-ok", "--sg-accent")


def test_the_brand_is_vendored_here():
    assert (BRAND / "stratigraph-theme.css").is_file(), "run ./sync-brand.sh"
    assert len(sorted((BRAND / "fonts").glob("*.woff2"))) == 8
    assert (BRAND / "logo" / "favicon-deep-charcoal.svg").is_file()


def test_the_vendored_brand_is_the_SHARED_one_and_was_not_edited_here():
    """One source of truth. A theme tweaked in a consumer is a fork nobody
    called a fork."""
    here = (BRAND / "stratigraph-theme.css").read_text(encoding="utf-8")
    shared = (pathlib.Path(__file__).resolve().parent.parent.parent
              / "stratigraph-brand" / "stratigraph-theme.css")
    if not shared.is_file():                    # no sibling checkout in CI
        assert "stratigraph-brand" in here
        return
    assert here == shared.read_text(encoding="utf-8"), \
        "app/brand/ has drifted from stratigraph-brand/ — re-run ./sync-brand.sh"


def test_the_page_reaches_no_cdn():
    for path in (PAGE, SHEET, APP / "ui" / "catalog.js"):
        code = re.sub(r"/\*.*?\*/|<!--.*?-->", "", path.read_text(encoding="utf-8"),
                      flags=re.S)
        for host in ("fonts.googleapis.com", "fonts.gstatic.com",
                     "api.fontshare.com", "cdn.fontshare.com",
                     "cdn.jsdelivr.net", "unpkg.com"):
            assert host not in code, f"{path.name} reaches {host}"


def test_the_theme_is_imported_relatively_so_it_survives_the_proxy():
    assert '@import url("../brand/stratigraph-theme.css")' in \
        SHEET.read_text(encoding="utf-8")


def test_the_stylesheet_names_no_colour():
    found = re.findall(r"#[0-9A-Fa-f]{3,8}\b", SHEET.read_text(encoding="utf-8"))
    assert not found, found


def test_the_only_hexes_in_the_page_are_the_two_theme_colors():
    source = PAGE.read_text(encoding="utf-8")
    found = {h.upper() for h in re.findall(r"#[0-9A-Fa-f]{3,8}\b", source)}
    assert found <= {"#F1EBE3", "#2E2D2C"} <= GUIDEBOOK | found
    for hexed in found:
        assert f'content="{hexed}"' in source


def test_no_text_sits_on_a_pure_accent():
    for line in SHEET.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith(("*", "/*", "//")) or "color-mix" in stripped:
            continue
        for accent in PURE_ACCENTS:
            assert not re.search(rf"(?<!-)\bcolor:\s*var\({accent}\)", stripped), \
                f"text on a pure accent — {stripped}"


def test_a_filled_button_is_charcoal_because_burnt_cannot_carry_text_this_size():
    sheet = SHEET.read_text(encoding="utf-8")
    assert "--fill:     var(--sg-deep-charcoal)" in sheet
    assert "--on-fill:  var(--sg-off-white)" in sheet


def test_the_page_wears_the_hourglass_and_the_display_face():
    source = PAGE.read_text(encoding="utf-8")
    assert "favicon-deep-charcoal.svg" in source
    assert 'class="wordmark">StratiGraph' in source
    assert "font-family: var(--sg-font-display)" in SHEET.read_text(encoding="utf-8")


def test_the_static_mounts_revalidate_rather_than_go_stale():
    """Ported from StratiGraph Server, where it was measured: ETag but no
    `Cache-Control` means a browser applies heuristic freshness and serves a
    stale stylesheet to a tab that is already open."""
    main = (APP / "main.py").read_text(encoding="utf-8")
    assert "class _FreshStatic(StaticFiles)" in main
    assert 'response.headers.setdefault("Cache-Control", "no-cache")' in main
    assert main.count("_FreshStatic(directory=") == 2, \
        "every StratiGraph-native mount must revalidate"


def test_the_views_read_the_PUBLIC_api_and_hold_no_token():
    """A catalogue whose purpose is discovery answers an anonymous caller. This
    page asks for nothing else — and holds no credential to ask with."""
    js = (APP / "ui" / "catalog.js").read_text(encoding="utf-8")
    assert "/studies?" in js
    for sink in ("localStorage", "document.cookie", "Authorization"):
        assert sink not in js, sink
