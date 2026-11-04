"use strict";
const CONSENT_KEY = "ikigai-tries-consent";
const VISITOR_KEY = "ikigai-tries-visitor";
const DELETE_KEY = "ikigai-tries-delete-key";
const ENDPOINT = "https://ikigai-tries.macayaven.workers.dev";
const PAGE_VERSION = "verify@e0a1fd7";

function readConsent() {
  try {
    const raw = localStorage.getItem(CONSENT_KEY);
    if (!raw) return null;
    const obj = JSON.parse(raw);
    if (obj && obj.v === 1 && (obj.choice === "yes" || obj.choice === "no")) return obj;
    return null;
  } catch (err) {
    return null;
  }
}

function writeConsent(choice) {
  try {
    localStorage.setItem(CONSENT_KEY, JSON.stringify({ v: 1, choice: choice }));
  } catch (err) {}
}

function isStudyMode() {
  try {
    return new URLSearchParams(window.location.search).get("src") === "prolific";
  } catch (err) {
    return false;
  }
}

function randomCode() {
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  const bytes = new Uint8Array(8);
  crypto.getRandomValues(bytes);
  return Array.from(bytes).map(function (b) { return alphabet[b % alphabet.length]; }).join("");
}

function randomKey() {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return Array.from(bytes).map(function (b) { return b.toString(16).padStart(2, "0"); }).join("");
}

function maskText(value) {
  if (typeof value !== "string") return value;
  let out = value;
  out = out.replace(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g, "[email]");
  out = out.replace(/https?:\/\/\S+/gi, "[url]");
  out = out.replace(/www\.\S+/gi, "[url]");
  out = out.replace(/\d{9,}/g, "[digits]");
  out = out.replace(/\+?[\d(][\d\s.\-()]*\d/g, function (m) {
    return m.replace(/\D/g, "").length >= 7 ? "[phone]" : m;
  });
  return out;
}

function maskCard(card) {
  if (!Array.isArray(card)) return card;
  return card.map(function (row) {
    if (row && typeof row === "object" && !Array.isArray(row)) {
      const out = {};
      for (const k in row) {
        out[k] = typeof row[k] === "string" ? maskText(row[k]) : row[k];
      }
      return out;
    }
    return row;
  });
}

async function sha256hex(text) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(buf)).map(function (b) { return b.toString(16).padStart(2, "0"); }).join("");
}

function getVisitor() {
  let v = null;
  try { v = localStorage.getItem(VISITOR_KEY); } catch (err) {}
  if (!v) {
    v = randomCode();
    try { localStorage.setItem(VISITOR_KEY, v); } catch (err) {}
  }
  return v;
}

function getDeleteKey() {
  let k = null;
  try { k = localStorage.getItem(DELETE_KEY); } catch (err) {}
  if (!k) {
    k = randomKey();
    try { localStorage.setItem(DELETE_KEY, k); } catch (err) {}
  }
  return k;
}

async function sendRow(row) {
  if (readConsent() && readConsent().choice !== "yes") return;
  const init = {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(row),
    keepalive: true,
  };
  try {
    const res = await fetch(ENDPOINT + "/v1/tries", init);
    if (!res.ok) return;
  } catch (err) {
    try {
      await fetch(ENDPOINT + "/v1/tries", init);
    } catch (err2) {}
  }
}

async function saveTry(payload) {
  if (!payload) return;
  const c = readConsent();
  if (!c || c.choice !== "yes") return;
  if (isStudyMode()) return;
  const visitor = getVisitor();
  const deleteKey = getDeleteKey();
  const deleteHash = await sha256hex(deleteKey);
  const codes = Array.isArray(payload.codes) ? payload.codes : [];
  const privateHit = codes.indexOf("L1_PII") !== -1 || codes.indexOf("L1_SECRET") !== -1 || codes.indexOf("L1_PRIVATE_TERM") !== -1;
  const sentence = String(payload.sentence == null ? "" : payload.sentence);
  const checked = String(payload.checked == null ? "" : payload.checked);
  const rawCard = payload.card == null ? [] : payload.card;
  const maskedSentence = privateHit ? "" : maskText(sentence);
  const maskedChecked = privateHit ? "" : maskText(checked);
  const card = maskCard(rawCard);
  const redacted = !!payload.redacted || privateHit || maskedSentence !== sentence || maskedChecked !== checked || JSON.stringify(card) !== JSON.stringify(rawCard);
  const row = {
    visitor: visitor,
    page_version: payload.pageVersion || PAGE_VERSION,
    consent_v: 1,
    mode: payload.mode === "game" ? "game" : "form",
    card: card,
    sentence: maskedSentence,
    verdict: payload.verdict === "FAIL" ? "FAIL" : "PASS",
    codes: Array.isArray(payload.codes) ? payload.codes : [],
    checked: maskedChecked,
    redacted: redacted,
    delete_hash: deleteHash,
  };
  if (payload.answer != null) row.answer = maskText(String(payload.answer));
  if (payload.beat_checker != null) row.beat_checker = !!payload.beat_checker;
  if (payload.note != null && String(payload.note).trim() !== "") {
    row.note = maskText(String(payload.note)).slice(0, 500);
  }
  await sendRow(row);
}

function updateFooter() {
  const el = document.getElementById("tries-status");
  if (!el) return;
  const c = readConsent();
  while (el.firstChild) el.removeChild(el.firstChild);
  if (c && c.choice === "yes") {
    el.append(document.createTextNode("Saving your tries: on \u00b7 "));
    const stop = document.createElement("button");
    stop.type = "button";
    stop.textContent = "Stop saving";
    stop.addEventListener("click", function () {
      writeConsent("no");
      updateFooter();
    });
    el.append(stop);
    el.append(document.createTextNode(" \u00b7 "));
    const del = document.createElement("button");
    del.type = "button";
    del.textContent = "Delete my tries";
    del.addEventListener("click", deleteTries);
    el.append(del);
  } else {
    el.append(document.createTextNode("Saving your tries: off \u00b7 "));
    const start = document.createElement("button");
    start.type = "button";
    start.textContent = "Start saving";
    start.addEventListener("click", function () {
      const panel = document.getElementById("tries-consent");
      if (panel) panel.removeAttribute("hidden");
    });
    el.append(start);
  }
}

async function deleteTries() {
  const visitor = (function () { try { return localStorage.getItem(VISITOR_KEY); } catch (e) { return null; } })();
  const key = (function () { try { return localStorage.getItem(DELETE_KEY); } catch (e) { return null; } })();
  if (!visitor) {
    writeConsent("no");
    updateFooter();
    return;
  }
  try {
    const res = await fetch(ENDPOINT + "/v1/visitors/" + encodeURIComponent(visitor) + "/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key: key }),
      keepalive: true,
    });
    if (res.ok) {
      try { localStorage.removeItem(VISITOR_KEY); } catch (e) {}
      try { localStorage.removeItem(DELETE_KEY); } catch (e) {}
      writeConsent("no");
      updateFooter();
      window.alert("Your saved tries were deleted.");
    }
  } catch (err) {}
}

function onYes() {
  getVisitor();
  getDeleteKey();
  writeConsent("yes");
  const panel = document.getElementById("tries-consent");
  if (panel) panel.setAttribute("hidden", "");
  updateFooter();
}

function onNo() {
  writeConsent("no");
  const panel = document.getElementById("tries-consent");
  if (panel) panel.setAttribute("hidden", "");
  updateFooter();
}

function init() {
  if (isStudyMode()) {
    const panel = document.getElementById("tries-consent");
    if (panel) panel.setAttribute("hidden", "");
    return;
  }
  const panel = document.getElementById("tries-consent");
  const c = readConsent();
  if (panel) {
    if (c) {
      panel.setAttribute("hidden", "");
    } else {
      panel.removeAttribute("hidden");
    }
  }
  const yes = document.getElementById("tries-yes");
  const no = document.getElementById("tries-no");
  if (yes) yes.addEventListener("click", onYes);
  if (no) no.addEventListener("click", onNo);
  updateFooter();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}

window.ikigaiTries = {
  saveTry: saveTry,
  readConsent: readConsent,
};
