import { apiFetch } from "./api.js";
import { state } from "./state.js";
import { stringsList, stringInput, saveBtn, stringCounter, searchResults, searchView } from "./dom.js";
import { escapeHtml, formatCreatedAt, getFromQuery, normalizeText, splitPrefixAndBody } from "./utils.js";
import { closePostModal, resetSaveButton, setSaveBtnState, showMsg, showOnly } from "./ui.js";
import { renderDetailError, renderThoughtDetail, updateThoughtDetail } from "./detail.js";

export const MAX_STRING_LENGTH = 50000;
const PENDING_THOUGHT_KEY = "pending-thought-submission";
const OWNER_POLL_INTERVAL_MS = 4000;
const TERMINAL_STATUSES = new Set(["mined", "reverted", "failed"]);
let ownerPollGeneration = 0;
let ownerPollTimer = null;

export function stopOwnThoughtPolling() {
  ownerPollGeneration += 1;
  if (ownerPollTimer !== null) clearTimeout(ownerPollTimer);
  ownerPollTimer = null;
}

function getIdempotencyKey(content) {
  try {
    const pending = JSON.parse(localStorage.getItem(PENDING_THOUGHT_KEY));
    if (pending?.content === content && pending?.key) return pending.key;
  } catch {
    localStorage.removeItem(PENDING_THOUGHT_KEY);
  }

  const key = crypto.randomUUID();
  localStorage.setItem(PENDING_THOUGHT_KEY, JSON.stringify({ content, key }));
  return key;
}

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

    const stringId = item.dataset.stringId;
    window.location.href = `/own/thoughts/${encodeURIComponent(stringId)}?from=overview`;
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
    const idempotencyKey = getIdempotencyKey(content);
    await apiFetch("/api/thoughts", {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({ content }),
    });

    localStorage.removeItem(PENDING_THOUGHT_KEY);
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
  stopOwnThoughtPolling();
  const generation = ownerPollGeneration;
  await loadAndRenderOwnThought(thoughtId, generation, true);
}

async function loadAndRenderOwnThought(thoughtId, generation, initial = false) {
  try {
    const data = await apiFetch(`/api/thoughts/${encodeURIComponent(thoughtId)}`);

    if (generation !== ownerPollGeneration) return;

    if (initial) {
      showOnly(searchView);
      searchResults.innerHTML = "";
      const ownUsername = data.username || state.currentUsername || "";
      const from = getFromQuery();
      const backHref = from === "overview" ? "/?view=overview" : `/${encodeURIComponent(ownUsername)}`;
      renderThoughtDetail(data, ownUsername, backHref);
    } else {
      updateThoughtDetail(data);
    }

    if (!TERMINAL_STATUSES.has(data.status)) {
      ownerPollTimer = setTimeout(async () => {
        if (generation !== ownerPollGeneration) return;
        if (document.hidden) {
          await loadAndRenderOwnThoughtWhenVisible(thoughtId, generation);
          return;
        }
        await loadAndRenderOwnThought(thoughtId, generation);
      }, OWNER_POLL_INTERVAL_MS);
    }
  } catch (err) {
    if (generation !== ownerPollGeneration) return;
    if (initial) {
      showOnly(searchView);
      searchResults.innerHTML = "";
      renderDetailError(err.message);
      return;
    }
    ownerPollTimer = setTimeout(
      () => loadAndRenderOwnThought(thoughtId, generation),
      OWNER_POLL_INTERVAL_MS,
    );
  }
}

async function loadAndRenderOwnThoughtWhenVisible(thoughtId, generation) {
  if (generation !== ownerPollGeneration) return;
  if (document.hidden) {
    ownerPollTimer = setTimeout(
      () => loadAndRenderOwnThoughtWhenVisible(thoughtId, generation),
      OWNER_POLL_INTERVAL_MS,
    );
    return;
  }
  await loadAndRenderOwnThought(thoughtId, generation);
}
