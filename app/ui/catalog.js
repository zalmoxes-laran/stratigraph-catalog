/**
 * The catalogue's two views (spec §4), against its own public API.
 *
 * `flat` is every study this caller may see; `hdt` groups one monument's
 * campaigns over time, which is the view the Heritage Digital Twin exists for —
 * Sarmizegetusa 1978, 2013, 2026 as one thing looked at three times.
 *
 * No token handling here, and that is deliberate: `/catalog/studies` answers an
 * anonymous caller with the PUBLIC studies, because a catalogue whose purpose is
 * discovery must answer somebody who has not logged in. Anything more needs a
 * token, and asking for one is a different page's job.
 */

/** The API, derived from where this page is served — the same reasoning as the
 *  node console's: `/catalog/ui/…` and a proxied `/catalog/ui/…` must both land
 *  on the API that served them. */
const BASE = window.location.pathname.replace(/\/ui(\/.*)?$/, "");

import { LOCALE, mountPicker, t } from "./i18n.js";

const $ = (id) => document.getElementById(id);
let view = "flat";

async function get(path) {
  const answer = await fetch(`${BASE}${path}`, {
    headers: { Accept: "application/json" },
  });
  const text = await answer.text();
  let payload = null;
  try { payload = text ? JSON.parse(text) : null; } catch { payload = null; }
  if (!answer.ok) {
    throw new Error((payload && payload.detail) || `HTTP ${answer.status}`);
  }
  return payload;
}

// ── drawing ─────────────────────────────────────────────────────────────────

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/** A study, as a card. */
function studyCard(study) {
  const box = el("article", "study");

  const head = el("div", "study-head");
  head.append(el("span", "study-title", study.title || study.id));
  // the PID is what somebody cites: mono, and never truncated away
  if (study.em_id) head.append(el("span", "pid", study.em_id));
  if (study.kind) head.append(el("span", "tag quiet", study.kind));
  if (study.visibility && study.visibility !== "public") {
    head.append(el("span", "tag embargo", study.visibility));
  }
  if (study.embargo_active) head.append(el("span", "tag embargo", t("study.embargo")));
  const licence = study.license_effective || study.license;
  if (licence) {
    const tag = el("span", "tag licence", licence);
    if (study.license_is_default) tag.title = t("licence.inherited");
    head.append(tag);
  }
  box.append(head);

  const authors = (study.authors || []).filter(Boolean);
  if (authors.length) {
    const line = el("div", "authors");
    authors.forEach((a, index) => {
      if (index) line.append(document.createTextNode(" · "));
      line.append(document.createTextNode(a.name || "—"));
      if (a.orcid) {
        line.append(document.createTextNode(" "));
        line.append(el("span", "orcid", a.orcid));
      }
    });
    box.append(line);
  }
  if (study.description) box.append(el("p", "desc", study.description));

  // ── open in… — the catalogue's own descriptor, not a URL built here ───────
  // `/study/{id}/open` decides what is real (a container URL that always works,
  // a scheme that may have no handler). A page that guessed would offer buttons
  // that fail after the click.
  const open = el("div", "open");
  const read = el("a", "btn", t("study.read"));
  read.href = `${BASE}/study/${encodeURIComponent(study.id)}/narrative`;
  read.title = t("study.read.title");
  const emjson = el("a", "btn ghost", "em.json");
  emjson.href = `${BASE}/study/${encodeURIComponent(study.id)}/emjson`;
  emjson.title = t("study.emjson.title");
  const ttl = el("a", "btn ghost", "RDF");
  ttl.href = `${BASE}/study/${encodeURIComponent(study.id)}/ttl`;
  ttl.title = t("study.ttl.title");
  open.append(read, emjson, ttl);

  if (view === "flat" && study.hc2 && study.hc2.id) {
    const twin = el("button", "ghost", t("hdt.campaigns"));
    twin.title = t("hdt.every", { name: study.hc2.name || study.hc2.id });
    twin.addEventListener("click", () => { showHdt(study.hc2.id); });
    open.append(twin);
  }
  box.append(open);
  return box;
}

/** One digital twin: its campaigns, most recent first. */
function twinGroup(group) {
  const box = el("section", "twin");
  const head = el("div", "twin-head");
  head.append(el("h2", null, (group.hc2 && group.hc2.name) || group.hc2?.id || "—"));
  if (group.hc2 && group.hc2.id) head.append(el("span", "pid", group.hc2.id));
  head.append(el("span", "tag", `${(group.studies || []).length} campaigns`));
  box.append(head);
  if (group.hc1 && group.hc1.name) {
    box.append(el("p", "twin-of", `of ${group.hc1.name}`));
  }
  const list = el("ol", "timeline");
  for (const study of group.studies || []) {
    const item = document.createElement("li");
    item.append(studyCard(study));
    list.append(item);
  }
  box.append(list);
  return box;
}

// ── the two views ───────────────────────────────────────────────────────────

function params() {
  const query = new URLSearchParams();
  const q = ($("q").value || "").trim();
  if (q) query.set("q", q);
  const licence = $("licence").value;
  if (licence) query.set("license", licence);
  return query;
}

async function showFlat() {
  view = "flat";
  $("heading").textContent = t("studies.title");
  $("lede").textContent = t("studies.sub");
  const query = params();
  query.set("view", "flat");
  await render(async () => {
    const data = await get(`/studies?${query}`);
    const studies = data.studies || [];
    if (!studies.length) return [el("p", "empty", t("studies.none"))];
    rememberLicences(studies);
    return studies.map(studyCard);
  });
}

async function showHdt(only) {
  view = "hdt";
  $("heading").textContent = t("hdt.title");
  $("lede").textContent = t("hdt.sub");
  const query = params();
  query.set("view", "hdt");
  await render(async () => {
    const data = await get(`/studies?${query}`);
    let groups = data.groups || [];
    if (only) groups = groups.filter((g) => g.hc2 && g.hc2.id === only);
    if (!groups.length) return [el("p", "empty", t("hdt.none"))];
    rememberLicences(groups.flatMap((g) => g.studies || []));
    return groups.map(twinGroup);
  });
}

async function render(build) {
  const out = $("out");
  out.innerHTML = "";
  out.append(el("p", "empty", t("loading")));
  let nodes;
  try {
    nodes = await build();
  } catch (error) {
    out.innerHTML = "";
    out.append(el("p", "empty err", t("unreachable", { error: error.message })));
    return;
  }
  out.innerHTML = "";
  nodes.forEach((n) => out.append(n));
}

/** The licence filter is built from what is THERE, not from a list somebody
 *  maintains: a catalogue that offered CC-BY-SA when nothing carries it teaches
 *  people the filter is broken. */
function rememberLicences(studies) {
  const select = $("licence");
  const seen = new Set([...select.options].map((o) => o.value).filter(Boolean));
  for (const study of studies) {
    const licence = study.license_effective || study.license;
    if (!licence || seen.has(licence)) continue;
    seen.add(licence);
    const option = document.createElement("option");
    option.value = licence;
    option.textContent = licence;
    select.append(option);
  }
}


// ── the screen, repainted in the active language ────────────────────────────
//
// The two views already write their own heading and lede, so this repaints the
// chrome around them and then asks the active view to draw itself again — a
// change of language must not cost a round trip.
function paintStrings() {
  document.documentElement.lang = LOCALE;
  document.title = t("app.title");
  $("app-sub").textContent = t("app.sub");
  $("view-flat").textContent = t("tab.studies");
  $("view-hdt").textContent = t("tab.hdt");
  $("q").placeholder = t("search.placeholder");
  $("q").setAttribute("aria-label", t("search.label"));
  $("licence").setAttribute("aria-label", t("licence.label"));
  const any = $("licence-any");
  if (any) any.textContent = t("licence.any");
  // …and the active view draws itself again, from the query it already has.
  void (view === "hdt" ? showHdt() : showFlat());
}

// ── wiring ──────────────────────────────────────────────────────────────────

$("view-flat").addEventListener("click", () => void showFlat());
$("view-hdt").addEventListener("click", () => void showHdt());
$("licence").addEventListener("change", () =>
  void (view === "hdt" ? showHdt() : showFlat()));
let typing = 0;
$("q").addEventListener("input", () => {
  window.clearTimeout(typing);
  // debounced: a catalogue that re-queried on every keystroke would make the
  // index the slowest thing about typing
  typing = window.setTimeout(() => void (view === "hdt" ? showHdt() : showFlat()), 250);
});

// The language first, with its picker: everything after is drawn once, in the
// right language, instead of flickering through English.
document.documentElement.lang = LOCALE;
mountPicker($("lang"), paintStrings);
paintStrings();
