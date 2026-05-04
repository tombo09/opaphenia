function escapeHtml(str) {
  return String(str ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function getStringIdFromUrl() {
  const params = new URLSearchParams(window.location.search);
  return params.get("stringId");
}

async function loadStringDetail() {
  const stringId = getStringIdFromUrl();
  const container = document.getElementById("stringDetail");

  if (!stringId) {
    container.innerHTML = "<p>Keine String-ID gefunden.</p>";
    return;
  }

  const res = await fetch(`/api/public/thoughts/${encodeURIComponent(stringId)}`);
  const data = await res.json().catch(() => ({}));

  if (!res.ok) {
    container.innerHTML = `<p>Fehler: ${escapeHtml(data.detail || "String konnte nicht geladen werden.")}</p>`;
    return;
  }

  container.innerHTML = `
    <div style="border:1px solid #ddd; padding:12px; margin-top:12px;">
      <div style="font-size:12px; opacity:0.7;">${escapeHtml(data.created_at)}</div>
      <div style="margin-top:8px;">${escapeHtml(data.content)}</div>
      <div>blocktime: ${escapeHtml(String(data.blocktime ?? ""))}</div>
      <div>hash: ${escapeHtml(String(data.hashed_string ?? ""))}</div>
      <div>txid: ${escapeHtml(String(data.txid ?? ""))}</div>
      <div><a href="${escapeHtml(String(data.etherscan_link ?? ""))}"target="_blank" rel="noopener noreferrer">etherscan Link</a></div>
    </div>
  `;
}

loadStringDetail();
