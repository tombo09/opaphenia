import { accountTimezone } from "./dom.js";
import { state } from "./state.js";

export function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

export function normalizeText(text) {
  return String(text ?? "")
    .normalize("NFC")
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n");
}

export function getFromQuery() {
  return new URLSearchParams(window.location.search).get("from");
}

export function getViewFromQuery() {
  return new URLSearchParams(window.location.search).get("view");
}

export function splitPrefixAndBody(text) {
  const value = String(text ?? "").trim();
  const lines = value.split("\n");

  if (lines.length <= 2) {
    return { prefix: value, body: "" };
  }

  return {
    prefix: lines.slice(0, 2).join("\n"),
    body: lines.slice(2).join("\n"),
  };
}

export function nl2brEscaped(text) {
  return escapeHtml(String(text ?? "")).replace(/\n/g, "<br>");
}

export function formatCreatedAt(value) {
  if (!value) return "";

  return new Date(value).toLocaleString("de-DE", {
    timeZone: state.currentTimezone || "Europe/Berlin",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatDateTimeWithSeconds(value) {
  if (!value) return "";

  const tz = accountTimezone?.value || state.currentTimezone || "Europe/Berlin";

  return new Date(value).toLocaleString("de-DE", {
    timeZone: tz,
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function proofHashText(body, username) {
  return `
INPUT
-----
text     = ${JSON.stringify(body)}
username = ${JSON.stringify(username)}
version  = 1

PYTHON
------
def with_prefix(text: str, username: str) -> str:
    prefix = f"v{version}\\n@{username}\\n\\n"
    return prefix + text

def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\\r\\n", "\\n").replace("\\r", "\\n")
    return text

def hash_string(text: str, username: str) -> str:
    normalized = normalize_text(with_prefix(text, username))
    return "0x" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()
`;
}
