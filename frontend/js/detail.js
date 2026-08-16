import { publicStringsList } from "./dom.js";
import { escapeHtml, formatDateTimeWithSeconds, proofHashText } from "./utils.js";
import { openProofHashModal, showMsg } from "./ui.js";

export function renderThoughtDetail(data, username, backHref) {
  const lines = String(data.content ?? "").trim().split("\n");
  const prefix = lines.slice(0, 2).join("\n").trim();
  const body = lines.slice(2).join("\n").trim();

  const publicUrl = data.public_url ||
    `/${encodeURIComponent(username)}/${encodeURIComponent(data.id)}`;
  publicStringsList.innerHTML = `
    <div class="card">
      <div class="public-thought-detail-box">
        <div class="detail-topbar">
          <a href="${backHref}">← back</a>
          <div class="detail-actions">
            <button id="copyLinkBtn" class="btn" type="button">copy link</button>
            <button id="proofHashBtn" class="btn" type="button">proof hash</button>
          </div>
        </div>

        <div class="detail-content-box">${(() => {
          if (lines.length <= 2) {
            return `<span class="detail-body">${escapeHtml(lines.join("\n").trim()).replace(/\n/g, "<br>")}</span>`;
          }
          return `<span class="detail-prefix">${escapeHtml(prefix).replace(/\n/g, "<br>")}</span><br><br><span class="detail-body">${escapeHtml(body).replace(/\n/g, "<br>")}</span>`;
        })()}</div>

        <div class="detail-meta">
          <div><span class="meta-label">blocktime</span><span class="meta-value" data-thought-field="blocktime">${escapeHtml(formatDateTimeWithSeconds(data.blocktime))}</span></div>
          <div><span class="meta-label">hash</span><span class="meta-value">${escapeHtml(String(data.hashed_string ?? ""))}</span></div>
          <div><span class="meta-label">txid</span><span class="meta-value" data-thought-field="txid">${escapeHtml(String(data.txid ?? ""))}</span></div>
          ${data.etherscan_link ? etherscanMarkup(data.etherscan_link) : ""}
        </div>
      </div>
    </div>
  `;

  attachDetailButtons(body, username, publicUrl);
}

export function updateThoughtDetail(data) {
  const blocktime = document.querySelector('[data-thought-field="blocktime"]');
  const txid = document.querySelector('[data-thought-field="txid"]');
  if (blocktime) blocktime.textContent = formatDateTimeWithSeconds(data.blocktime);
  if (txid) txid.textContent = String(data.txid ?? "");

  const currentLink = document.querySelector('[data-thought-field="etherscan_link"]');
  if (currentLink && data.etherscan_link) currentLink.href = data.etherscan_link;
  if (!currentLink && data.etherscan_link && txid) {
    txid.parentElement.insertAdjacentHTML("afterend", etherscanMarkup(data.etherscan_link));
  }
}

function etherscanMarkup(url) {
  return `<div><span class="meta-label">link</span><a class="meta-value" data-thought-field="etherscan_link" href="${escapeHtml(String(url))}" target="_blank" rel="noopener noreferrer">etherscan</a></div>`;
}

export function renderDetailError(message) {
  publicStringsList.innerHTML = `
    <div class="card">
      <p>Fehler: ${escapeHtml(message || "The string could not be loaded.")}</p>
    </div>
  `;
}

function attachDetailButtons(body, username, publicUrl) {
  document.getElementById("copyLinkBtn")?.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(new URL(publicUrl, window.location.origin).href);
      showMsg("Link copied!", 2000);
    } catch {
      showMsg("Copy failed", 2000);
    }
  });

  document.getElementById("proofHashBtn")?.addEventListener("click", () => {
    openProofHashModal(proofHashText(body, username));
  });
}
