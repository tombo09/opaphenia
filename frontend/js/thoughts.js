import { apiFetch } from "./api.js";
import { state } from "./state.js";
import { stringsList, stringInput, saveBtn, stringCounter, searchResults, searchView } from "./dom.js";
import { escapeHtml, formatCreatedAt, getFromQuery, normalizeText, splitPrefixAndBody } from "./utils.js";
import { closePostModal, resetSaveButton, setSaveBtnState, showMsg, showOnly } from "./ui.js";
import { renderDetailError, renderThoughtDetail } from "./detail.js";

export const MAX_STRING_LENGTH = 500;

export function initThoughtEvents() {
  if (stringInput) {
    stringInput.setAttribute("maxlength", String(MAX_STRING_LENGTH));
    stringInput.addEventListener("input", updateStringCounter);
    updateStringCounter();
  }

  saveBtn?.addEventListener("click", saveThought);

  stringsList?.addEventListener("click", async (e) => {
    const item = e.target.closest(".ownStringItem");
    if (!item) return;

    const username = state.currentUsername;
    if (!username) {
      showMsg("The username could not be loaded.", 3000);
      return;
    }

    const stringId = item.dataset.stringId;
    window.location.href = `/${encodeURIComponent(username)}/${encodeURIComponent(stringId)}?from=overview`;
  });
}

function updateStringCounter() {
  if (!stringInput || !stringCounter) return;
  stringCounter.textContent = `${stringInput.value.length} / ${MAX_STRING_LENGTH}`;
}

export async function refreshStringsList() {
  const data = await apiFetch("/api/thoughts");

  stringsList.innerHTML = data.items.length
    ? `
      <div class="stringsListBox">
        ${data.items
          .map((t) => {
            const parts = splitPrefixAndBody(t.content);
            return `
              <div class="ownStringItem" data-string-id="${t.id}">
                <div class="stringItemDate">${escapeHtml(formatCreatedAt(t.created_at))}</div>
                <div class="stringItemContent">${escapeHtml(parts.body)}</div>
              </div>
            `;
          })
          .join("")}
      </div>
    `
    : "<p>No entries yet</p>";
}

async function saveThought(e) {
  e.preventDefault();

  if (state.isSaving) return;

  const content = normalizeText(stringInput.value);

  if (!content) {
    showMsg("Please enter a string.", 3000);
    return;
  }

  if (content.length > MAX_STRING_LENGTH) {
    showMsg(`A maximum of ${MAX_STRING_LENGTH} characters are allowed.`, 3000);
    return;
  }

  state.isSaving = true;
  saveBtn.disabled = true;
  setSaveBtnState("loading");

  try {
    await apiFetch("/api/thoughts", {
      method: "POST",
      body: JSON.stringify({ content }),
    });

    setSaveBtnState("success");
    showMsg(`saved!`, 3000);
    stringInput.value = "";
    updateStringCounter();
    await refreshStringsList();

    setTimeout(() => closePostModal(), 900);
  } catch (err) {
    setSaveBtnState("error");
    showMsg(err.message || "Error saving.", 3000);
    setTimeout(() => resetSaveButton(), 900);
  }
}

export async function loadOwnThoughtDetail(thoughtId) {
  try {
    const data = await apiFetch(`/api/thoughts/${encodeURIComponent(thoughtId)}`);

    showOnly(searchView);
    searchResults.innerHTML = "";

    const ownUsername = data.username || state.currentUsername || "";
    const from = getFromQuery();
    const backHref = from === "overview" ? "/?view=overview" : `/${encodeURIComponent(ownUsername)}`;

    renderThoughtDetail(data, ownUsername, backHref);
  } catch (err) {
    showOnly(searchView);
    searchResults.innerHTML = "";
    renderDetailError(err.message);
  }
}
