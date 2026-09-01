/**
 * SIX LANGUAGES, and English is the source.
 *
 * Beside it, the languages of the project's case studies (T2.3) — `it` `ro` `el`
 * `es` `pl` — because those are the languages somebody will actually excavate
 * in. `en` and `it` are complete; the other four carry THE SAME KEYS with empty
 * values, which fall back to English.
 *
 * That is not laziness: **translating is the partners' work**, each for their own
 * language and their own dig. A string invented by us in a language none of us
 * re-reads is worse than the English it replaced. We build the slot, and a test
 * keeps it from having holes.
 *
 * **One convention, one implementation per surface** — this is the catalogue's.
 * The room server's two faces share one of these, and the field assistant keeps
 * its dictionaries INLINE because it is one HTML file on purpose. A library
 * across the three stacks would be the fifth place to keep aligned; if a fourth
 * surface appears, the report of 2026-09-01 says where it would live.
 *
 * **No endpoint serves this.** A surface that has to ask somebody how to say
 * "Read" does not speak offline.
 *
 * The choice lives in `localStorage`: the language is not a credential, and it
 * belongs to the DEVICE and not to the person. See
 * `stratigraph-brand/GLOSSARY.md` for the words the four faces share, and for
 * what is never translated — US, DTC, HDT, ORCID, `crmdig:D7` are TERMS, not
 * text, and a translated term is a term lost.
 */

export const LOCALES = ["en", "it", "ro", "el", "es", "pl"];
export const LOCALE_NAMES = { en: "English", it: "Italiano", ro: "Română",
                              el: "Ελληνικά", es: "Español", pl: "Polski" };
const LOCALE_KEY = "sg.locale.v1";

const STRINGS = {
  en: {
    "app.title": "Studies · StratiGraph catalogue",
    "app.sub": "catalogue",
    "tab.studies": "Studies",
    "tab.hdt": "By HDT",
    "studies.title": "Studies",
    "studies.sub": "Everything this catalogue has published.",
    "studies.none": "No studies match.",
    "hdt.title": "By HDT — Heritage Digital Twins",
    "hdt.sub": "One heritage object, its campaigns over time — the view the digital twin exists for.",
    "hdt.none": "Nothing grouped by a digital twin yet.",
    "hdt.campaigns": "Campaigns",
    "hdt.every": "Every study of {name}, over time",
    "search.placeholder": "Search titles, authors, places…",
    "search.label": "Search studies",
    "licence.label": "Filter by licence",
    "licence.any": "Any licence",
    "licence.inherited": "inherited: the study names none",
    "loading": "Loading…",
    "unreachable": "Cannot reach the catalogue: {error}",
    "study.read": "Read",
    "study.read.title": "The study as a story — EMStudio's reader, live",
    "study.emjson.title": "The container itself: what every tool opens",
    "study.ttl.title": "The CIDOC projection, as Turtle",
    "study.embargo": "under embargo",
    "lang.label": "Language",
  },
  it: {
    "app.title": "Studi · catalogo StratiGraph",
    "app.sub": "catalogo",
    "tab.studies": "Studi",
    "tab.hdt": "Per HDT",
    "studies.title": "Studi",
    "studies.sub": "Tutto quello che questo catalogo ha pubblicato.",
    "studies.none": "Nessuno studio corrisponde.",
    "hdt.title": "Per HDT — Heritage Digital Twins",
    "hdt.sub": "Un oggetto del patrimonio, le sue campagne nel tempo — la vista per cui il gemello digitale esiste.",
    "hdt.none": "Ancora nulla raggruppato per gemello digitale.",
    "hdt.campaigns": "Campagne",
    "hdt.every": "Ogni studio di {name}, nel tempo",
    "search.placeholder": "Cerca titoli, autori, luoghi…",
    "search.label": "Cerca negli studi",
    "licence.label": "Filtra per licenza",
    "licence.any": "Qualunque licenza",
    "licence.inherited": "ereditata: lo studio non ne dichiara una",
    "loading": "Sto caricando…",
    "unreachable": "Non raggiungo il catalogo: {error}",
    "study.read": "Leggi",
    "study.read.title": "Lo studio come racconto — il lettore di EMStudio, dal vivo",
    "study.emjson.title": "Il contenitore stesso: quello che ogni strumento apre",
    "study.ttl.title": "La proiezione CIDOC, in Turtle",
    "study.embargo": "sotto embargo",
    "lang.label": "Lingua",
  },
  // ── the partners' slots: same keys, empty values, falling back to `en` ──────
  ro: {}, el: {}, es: {}, pl: {},
};

for (const code of LOCALES) {
  for (const key of Object.keys(STRINGS.en)) {
    if (!(key in STRINGS[code])) STRINGS[code][key] = "";
  }
}

function pick() {
  try {
    const saved = localStorage.getItem(LOCALE_KEY);
    if (saved && LOCALES.includes(saved)) return saved;
  } catch { /* no storage: the browser's own language decides */ }
  const asked = (navigator.language || "en").slice(0, 2).toLowerCase();
  return LOCALES.includes(asked) ? asked : "en";
}

export let LOCALE = pick();

export function t(key, values) {
  const text = (STRINGS[LOCALE] && STRINGS[LOCALE][key]) || STRINGS.en[key] || key;
  return values
    ? text.replace(/\{(\w+)\}/g, (_m, name) => String(values[name] ?? ""))
    : text;
}

export function setLocale(code, onChange) {
  if (!LOCALES.includes(code)) return;
  LOCALE = code;
  try { localStorage.setItem(LOCALE_KEY, code); } catch { /* nothing to do */ }
  document.documentElement.lang = code;
  if (onChange) onChange();
}

/** The picker, each option written IN its own language: somebody who cannot read
 *  the current one must still find theirs in the list. */
export function mountPicker(select, onChange) {
  if (!select) return;
  select.innerHTML = "";
  select.setAttribute("aria-label", t("lang.label"));
  for (const code of LOCALES) {
    const option = document.createElement("option");
    option.value = code;
    option.textContent = LOCALE_NAMES[code];
    if (code === LOCALE) option.selected = true;
    select.appendChild(option);
  }
  select.addEventListener("change", () => setLocale(select.value, onChange));
}
