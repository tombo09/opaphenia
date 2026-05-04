import { apiRaw } from "./api.js";
import { searchAccInput, searchAccBtn, searchResults, publicStringsList, searchView } from "./dom.js";
import { escapeHtml, formatCreatedAt, getFromQuery, splitPrefixAndBody } from "./utils.js";
import { showMsg, showOnly } from "./ui.js";
import { renderDetailError, renderThoughtDetail } from "./detail.js";

let searchDebounce;

export function initPublicEvents() {
  searchAccInput?.addEventListener("input", () => {
    clearTimeout(searchDebounce);
    searchDebounce = setTimeout(runSearch, 200);
  });

  searchAccInput?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") runSearch();
  });

  document.addEventListener("click", (e) => {
    const clickedInsideSearch =
      e.target === searchAccInput ||
      e.target === searchAccBtn ||
      e.target.closest("#searchResults");

    if (!clickedInsideSearch && searchResults) {
      searchResults.style.display = "none";
    }
  });

  publicStringsList?.addEventListener("click", (e) => {
    const item = e.target.closest(".stringItem");
    if (!item) return;

    const stringId = item.dataset.stringId;
    const username = item.dataset.username;
    window.location.href = `/${encodeURIComponent(username)}/${encodeURIComponent(stringId)}`;
  });
}

export async function runSearch() {
  const q = searchAccInput.value.trim();

  if (!q) {
    searchResults.innerHTML = "";
    searchResults.style.display = "none";
    publicStringsList.innerHTML = "";
    return;
  }

  const res = await apiRaw(`/api/public/search?q=${encodeURIComponent(q)}`);
  const data = await res.json().catch(() => ({}));

  if (!res.ok) {
    searchResults.innerHTML = "";
    searchResults.style.display = "none";
    showMsg(data.detail || "Search error", 3000);
    return;
  }

  if (!data.items || data.items.length === 0) {
    searchResults.innerHTML = "";
    searchResults.style.display = "none";
    return;
  }

  searchResults.innerHTML = data.items
    .map(
      (u) => `
        <button class="accItem" data-user-id="${u.id}" data-username="${u.username}" type="button">
          ${escapeHtml(u.username)}
        </button>
      `
    )
    .join("");

  searchResults.style.display = "block";

  document.querySelectorAll(".accItem").forEach((btn) => {
    btn.addEventListener("click", () => {
      const username = btn.dataset.username;
      window.location.href = `/${encodeURIComponent(username)}`;
    });
  });
}

export async function loadPublicThoughtsByUsername(username) {
  const res = await apiRaw(`/api/public/user/${encodeURIComponent(username)}`);
  const data = await res.json().catch(() => ({}));

  if (!res.ok) {
    searchResults.innerHTML = "";
    publicStringsList.innerHTML = "";
    showMsg(data.detail || "Error loading user", 3000);
    showOnly(searchView);
    return;
  }

  showOnly(searchView);

  searchResults.innerHTML = "";
  publicStringsList.innerHTML = `
    <div class="publicStringsHeader">
      <strong>@${escapeHtml(data.user.username)}</strong>
    </div>
    ${
      data.items.length
        ? `
          <div class="stringsListBox">
            ${data.items
              .map((t) => {
                const parts = splitPrefixAndBody(t.content);
                return `
                  <div class="stringItem" data-string-id="${t.id}" data-username="${data.user.username}">
                    <div class="stringItemDate">${escapeHtml(formatCreatedAt(t.created_at))}</div>
                    <div class="stringItemContent">${escapeHtml(parts.body)}</div>
                  </div>
                `;
              })
              .join("")}
          </div>
        `
        : "<p>No strings.</p>"
    }
  `;
}

export async function loadPublicThoughtDetail(username, thoughtId) {
  const res = await apiRaw(
    `/api/public/user/${encodeURIComponent(username)}/thoughts/${encodeURIComponent(thoughtId)}`
  );
  const data = await res.json().catch(() => ({}));

  showOnly(searchView);
  searchResults.innerHTML = "";

  const from = getFromQuery();
  const backHref = from === "overview" ? "/?view=overview" : `/${encodeURIComponent(username)}`;

  if (!res.ok) {
    renderDetailError(data.detail || "The string could not be loaded.");
    return;
  }

  renderThoughtDetail(data, username, backHref);
}
