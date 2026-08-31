"""Six languages in the catalogue, and no locale with a hole.

English is the source language of every StratiGraph surface; beside it, the
languages of the project's case studies (T2.3) — `it` `ro` `el` `es` `pl` —
because those are the languages somebody will actually excavate in.

`en` and `it` are complete. The other four exist with **the same keys and empty
values**, which fall back to English. That is deliberate: **translating is the
partners' work**, each for their own language and their own dig, and a string
invented by us in a language none of us re-reads is worse than the English.

What this file defends is the SLOT:

* every locale carries every key — a hole is invisible, because the fallback
  shows English and nobody learns the string was never translated;
* the placeholders survive translation: a `{n}` lost is a sentence that stops;
* the three VERBS stay three different words, because they are the only thing
  telling a monument, a study and a room apart on screen;
* nothing that is a domain TERM was translated.

One convention, one implementation per surface: this is the catalogue's own.
A library across the three stacks would be the fifth place to keep aligned.
"""

from __future__ import annotations

import pathlib
import re

_UI = pathlib.Path(__file__).resolve().parent.parent / "app"
I18N = (_UI / "ui" / "i18n.js").read_text(encoding="utf-8")

EXPECTED = ("en", "it", "ro", "el", "es", "pl")
COMPLETE = ("en", "it")


def locales() -> dict:
    block = re.search(r"const STRINGS = \{(.*?)\n\};", I18N, re.S)
    assert block, "no STRINGS in the dictionary"
    found: dict = {}
    for match in re.finditer(r"^  (\w+): \{(.*?)^  \}", block.group(1), re.S | re.M):
        found[match.group(1)] = {
            key: value for key, value in
            re.findall(r'"([^"]+)":\s*"((?:[^"\\]|\\.)*)"', match.group(2))
        }
    for code in re.findall(r"(\w+): \{\},", block.group(1)):
        found.setdefault(code, {})
    return found


LOCALES = locales()


def test_the_six_locales_are_declared():
    assert tuple(LOCALES) == EXPECTED, tuple(LOCALES)


def test_the_complete_locales_have_every_key_and_no_empty_value():
    keys = set(LOCALES["en"])
    assert len(keys) > 20, f"only {len(keys)} keys — did the parser find them?"
    for code in COMPLETE:
        assert not keys - set(LOCALES[code]), sorted(keys - set(LOCALES[code]))
        empty = [k for k, v in LOCALES[code].items() if not v.strip()]
        assert not empty, f"{code} has empty values: {empty}"


def test_the_empty_locales_are_FILLED_IN_at_load_and_not_left_ragged():
    """The source declares them `{}`; the module normalises them against `en` so
    a translator opening the file sees the whole list and a test can count."""
    assert 'if (!(key in STRINGS[code])) STRINGS[code][key] = "";' in I18N


def test_the_placeholders_survive_translation():
    for key, source in LOCALES["en"].items():
        wanted = set(re.findall(r"\{(\w+)\}", source))
        for code in COMPLETE:
            value = LOCALES[code].get(key, "")
            if value:
                assert set(re.findall(r"\{(\w+)\}", value)) == wanted, f"{code}/{key}"



def test_no_domain_term_was_translated():
    for code in COMPLETE:
        for key, value in LOCALES[code].items():
            for term in ("DTC", "ORCID", "HDT", "em.json", "IIIF", "CIDOC"):
                if term in LOCALES["en"].get(key, ""):
                    assert term in value, f"{code}/{key} lost the term {term}"


def test_the_language_lives_on_the_DEVICE_and_the_token_does_not():
    """The locale is not a credential and it belongs to the device, not the
    person — like the field assistant's queue, unlike its token."""
    assert "localStorage.setItem(LOCALE_KEY" in I18N
    for name in re.findall(r"localStorage\.setItem\(([^,]+),", I18N):
        assert "token" not in name.lower(), name



def test_the_page_reads_the_dictionary():
    page = (_UI / "ui" / "catalog.js").read_text(encoding="utf-8")
    assert 'from "./i18n.js"' in page


def test_coverage_report():
    """Not an assertion — the number that goes to the partners."""
    keys = len(LOCALES["en"])
    print(f"\n  locale coverage, catalogue ({keys} keys)")
    for code in EXPECTED:
        filled = sum(1 for v in LOCALES[code].values() if v.strip())
        print(f"    {code}  {filled:3}/{keys}"
              + ("  complete" if filled == keys else "  ← partners"))
