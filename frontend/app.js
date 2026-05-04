// Elements

const homeBtn = document.getElementById("homeBtn");
const accountBtn = document.getElementById("accountBtn");
const logoutBtn = document.getElementById("logoutBtn");
const overviewBtn = document.getElementById("overviewBtn");

const searchAccInput = document.getElementById("searchAccInput");
const searchAccBtn = document.getElementById("searchAccBtn");
const searchResults = document.getElementById("searchResults");
const publicStringsList = document.getElementById("publicStringsList");

const loginView = document.getElementById("loginView");
const signupView = document.getElementById("signupView");
const overviewView = document.getElementById("overviewView");
const accountView = document.getElementById("accountView");
const searchView = document.getElementById("searchView");

const loginInput = document.getElementById("loginInput");
const loginPasswordInput = document.getElementById("loginPasswordInput");
const loginBtn = document.getElementById("loginBtn");
const openSignupBtn = document.getElementById("openSignupBtn");
const resetPwBtn = document.getElementById("resetPwBtn");

const signupEmailInput = document.getElementById("signupEmailInput");
const signupUsernameInput = document.getElementById("signupUsernameInput");
const signupPasswordInput = document.getElementById("signupPasswordInput");
const signupBtn = document.getElementById("signupBtn");
const backToLoginBtn = document.getElementById("backToLoginBtn");

const stringsList = document.getElementById("stringsList");
const stringInput = document.getElementById("stringInput");
const saveBtn = document.getElementById("saveBtn");

const accountEmail = document.getElementById("accountEmail");
const saveEmailBtn = document.getElementById("saveEmailBtn");
const cancelEmailBtn = document.getElementById("cancelEmailBtn");
const publicStringsChk = document.getElementById("publicStringsChk");
const saveVisibilityBtn = document.getElementById("saveVisibilityBtn");
const oldPw = document.getElementById("oldPw");
const newPw = document.getElementById("newPw");
const newPw2 = document.getElementById("newPw2");
const savePwBtn = document.getElementById("savePwBtn");
const openPostModalBtn = document.getElementById("openPostModalBtn");
const postModalOverlay = document.getElementById("postModalOverlay");
const closePostModalBtn = document.getElementById("closePostModalBtn");
const homeView = document.getElementById("homeView");

let originalEmail = "";
let failedLocal = 0;
let currentUsername = "";

// Helpers
const msg = document.getElementById("msgToast");
let msgTimer = null;
let msgClearTimer = null;

function showMsg(text, ms = 5000) {
  if (!msg) return;

  if (msgTimer) clearTimeout(msgTimer);
  if (msgClearTimer) clearTimeout(msgClearTimer);

  msg.textContent = text;
  msg.classList.add("show");

  if (!ms) return;

  msgTimer = setTimeout(() => {
    msg.classList.remove("show");

    msgClearTimer = setTimeout(() => {
      if (!msg.classList.contains("show")) {
        msg.textContent = "";
      }
    }, 200);
  }, ms);
}

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function parseRoute() {
  const parts = window.location.pathname
    .replace(/^\/+|\/+$/g, "")
    .split("/")
    .filter(Boolean);

  if (parts.length === 0) {
    return { type: "home" };
  }

  if (parts[0] === "index.html" || parts[0] === "subpage.html") {
    return { type: "home" };
  }

  if (parts.length === 1 && parts[0] === "settings") {
    return { type: "settings" };
  }

  if (parts.length === 1) {
    return {
      type: "user",
      username: decodeURIComponent(parts[0]),
    };
  }

  if (parts.length === 2) {
    return {
      type: "thought",
      username: decodeURIComponent(parts[0]),
      thoughtId: decodeURIComponent(parts[1]),
    };
  }

  return { type: "home" };
}
let isSaving = false;

function setSaveBtnState(state) {
  saveBtn.classList.remove("loading", "success", "error");
  if (state) saveBtn.classList.add(state);
}

function resetSaveButton() {
  isSaving = false;
  saveBtn.disabled = false;
  setSaveBtnState(null);
}

function openPostModal() {
  resetSaveButton();
  postModalOverlay.style.display = "flex";

  requestAnimationFrame(() => {
    stringInput.focus();
    stringInput.setSelectionRange(
      stringInput.value.length,
      stringInput.value.length
    );
  });
}

function closePostModal() {
  resetSaveButton();
  postModalOverlay.style.display = "none";
}

openPostModalBtn.addEventListener("click", () => {
  openPostModal();
});

closePostModalBtn.addEventListener("click", () => {
  closePostModal();
});

postModalOverlay.addEventListener("click", (e) => {
  if (e.target === postModalOverlay) {
    closePostModal();
  }
});

function openProofHashModal(content) {
  const modal = document.getElementById("proofHashModal");
  const codeBox = document.getElementById("proofHashCodeBox");
  if (!modal || !codeBox) return;

  codeBox.textContent = content;
  modal.style.display = "flex";
}

function closeProofHashModal() {
  const modal = document.getElementById("proofHashModal");
  if (!modal) return;
  modal.style.display = "none";
}


const proofHashModal = document.getElementById("proofHashModal");
if (proofHashModal) {
  proofHashModal.addEventListener("click", (e) => {
    if (e.target === proofHashModal) {
      closeProofHashModal();
    }
  });
}


function setAccountButtonDisabled(disabled) {
  if (!accountBtn) return;
  accountBtn.disabled = disabled;
}
const views = [homeView, loginView, signupView, overviewView, accountView, searchView];
function showOnly(viewEl) {
  views.forEach(v => {
    v.style.display = "none";
  });
    if (viewEl === loginView || viewEl === signupView || viewEl === accountView) {
    viewEl.style.display = "flex";
  } else {
    viewEl.style.display = "block";
  }
  const typingTitle = document.getElementById("typingTitle");

  if (viewEl === homeView) {
    startTypingWords(
      document.getElementById("typingTitle"),
      [
        { text: "If this page is forced to disappear your strings/words/work remain", className: "typingPos1" },
        { text: "this is not for fast pace typing aka doing writing mistakes i want to change it after few seconds environment", className: "typingPos2" },
        { text: "this project runs as long some people believe in it ", className: "typingPos3" }

        
      ],
      80,
      3000
    );
  } else {
    stopTypingLoop();
    if (typingTitle) typingTitle.textContent = "";
  }

  setHomeButtonDisabled(viewEl === overviewView || viewEl === homeView);
  setAccountButtonDisabled(viewEl === accountView);
}

async function isLoggedIn() {
  const res = await fetch("/api/me", { credentials: "include" });
  return res.ok;
}
function setHomeButtonDisabled(disabled) {
  homeBtn.disabled = disabled;
}
async function refreshAuthUI() {
  const ok = await isLoggedIn();
  logoutBtn.style.display = ok ? "inline-block" : "none";
  // overviewBtn.style.display = ok ? "inline-block" : "none";
  overviewBtn.style.display = "none";
}
const accountTimezone = document.getElementById("accountTimezone");
const saveTimezoneBtn = document.getElementById("saveTimezoneBtn");
let currentTimezone = null;
async function loadAccount() {
  const res = await fetch("/api/account", { credentials: "include" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    showMsg(data.detail || "Account konnte nicht geladen werden.", 3000);
    return false;
  }
  originalEmail = data.email;
  currentUsername = data.username;
  accountEmail.value = data.email;
  publicStringsChk.checked = !!data.strings_public;
  currentTimezone = data.timezone || "Europe/Berlin";
  accountTimezone.value = currentTimezone;
  const accountUsernameEl = document.getElementById("accountUsername");
  if (accountUsernameEl) {
    accountUsernameEl.textContent = `@${data.username}`;
  }

  return true;
}

function setEmailEditMode(on) {
  accountEmail.readOnly = !on;
  saveEmailBtn.style.display = on ? "inline-block" : "none";
  cancelEmailBtn.style.display = on ? "inline-block" : "none";
  if (on) accountEmail.focus();
}

homeBtn.addEventListener("click", async () => {
  history.pushState({}, "", "/");

  if (await isLoggedIn()) {
    showOnly(overviewView);
    await refreshStringsList();
  } else {
    showOnly(homeView);
  }
});

accountBtn.addEventListener("click", async () => {
  if (await isLoggedIn()) {
    history.pushState({}, "", "/settings");
    await initApp();
  } else {
    setHomeButtonDisabled(false);
    showOnly(loginView);
    loginInput.value = "";
    loginPasswordInput.value = "";
  }
});

window.addEventListener("popstate", () => {
  initApp();
});

overviewBtn.addEventListener("click", async () => {
  if (!(await isLoggedIn())) {
    showOnly(loginView);
    return;
  }
showOnly(overviewView);
await refreshStringsList();
});

logoutBtn.addEventListener("click", async () => {
  await fetch("/api/logout", { method: "POST", credentials: "include" });
  showMsg("Ausgeloggt.", 3000);
  await refreshAuthUI();
  window.location.href = "/";
});

// Login / Signup switching
openSignupBtn.addEventListener("click", () => {
  showOnly(signupView);
  signupEmailInput.value = "";
  signupUsernameInput.value = "";
  signupPasswordInput.value = "";
});

backToLoginBtn.addEventListener("click", () => {
  showOnly(loginView);
});

// Login
function lockLoginUI(locked) {
  loginPasswordInput.disabled = locked;
  loginBtn.disabled = locked;
  resetPwBtn.style.display = locked ? "inline-block" : "none";
}

loginBtn.addEventListener("click", async () => {
  const login = loginInput.value.trim();
  const password = loginPasswordInput.value;

  const res = await fetch("/api/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ login, password })
  });

  const data = await res.json().catch(() => ({}));

  if (!res.ok) {
    failedLocal++;
    if (res.status === 423) {
      lockLoginUI(true);
      showMsg(data.detail || "Zu viele Fehlversuche. Reset nötig.", 5000);
      return;
    }
    showMsg(data.detail || "Login fehlgeschlagen", 3000);
    if (failedLocal >= 5) resetPwBtn.style.display = "inline-block";
    return;
  }

  failedLocal = 0;
  lockLoginUI(false);
  loginInput.value = "";
  loginPasswordInput.value = "";
  showMsg("Eingeloggt.", 2000);
  window.location.href = "/";
});

// Reset
resetPwBtn.addEventListener("click", async () => {
  const email = loginInput.value.trim();
  if (!email) {
    showMsg("Bitte Email eingeben.", 3000);
    return;
  }

  await fetch("/api/password-reset/request", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email })
  });

  showMsg("Wenn ein Reset möglich ist, wurde eine Email gesendet.", 5000);
});

// Signup
signupBtn.addEventListener("click", async () => {
  const email = signupEmailInput.value.trim();
  const username = signupUsernameInput.value.trim();
  const password = signupPasswordInput.value;

  const res = await fetch("/api/signup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, username, password })
  });

  const data = await res.json().catch(() => ({}));

  if (res.status === 409) {
    showMsg(data.detail || "Email oder Username ist bereits vergeben.", 3000);
    return;
  }
  if (!res.ok) {
    showMsg(data.detail || "Fehler beim Erstellen.", 3000);
    return;
  }

  showMsg(data.message || "Bitte Email verifizieren.", 5000);
  showOnly(loginView);
});

// Account edit email
accountEmail.addEventListener("dblclick", () => setEmailEditMode(true));

cancelEmailBtn.addEventListener("click", () => {
  accountEmail.value = originalEmail;
  setEmailEditMode(false);
});

saveEmailBtn.addEventListener("click", async () => {
  const email = accountEmail.value.trim();

  const res = await fetch("/api/account/request-email-change", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ email })
  });

  const data = await res.json().catch(() => ({}));

  if (res.status === 409) {
    showMsg("Email existiert bereits.", 3000);
    return;
  }
  if (!res.ok) {
    showMsg(data.detail || "Email konnte nicht geändert werden.", 3000);
    return;
  }

  setEmailEditMode(false);
  showMsg("Bestätigungslink wurde an die neue Email gesendet. Bitte verifizieren.", 5000);
});

// Account visibility
saveVisibilityBtn.addEventListener("click", async () => {
  const res = await fetch("/api/account/visibility", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ strings_public: publicStringsChk.checked })
  });

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    showMsg(data.detail || "Konnte nicht speichern.", 3000);
    return;
  }
  showMsg(data.strings_public ? "Strings sind jetzt public." : "Strings sind jetzt private.", 3000);
});

// Account password
savePwBtn.addEventListener("click", async () => {
  const payload = {
    old_password: oldPw.value,
    new_password: newPw.value,
    new_password2: newPw2.value
  };

  const res = await fetch("/api/account/password", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(payload)
  });

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    showMsg(data.detail || "Passwort konnte nicht geändert werden.", 3000);
    return;
  }

  oldPw.value = "";
  newPw.value = "";
  newPw2.value = "";
  showMsg("Passwort geändert.", 3000);
});

saveTimezoneBtn?.addEventListener("click", async () => {
  const timezone = accountTimezone.value;

  const res = await fetch("/api/account/timezone", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ timezone })
  });

  const data = await res.json().catch(() => ({}));

  if (!res.ok) {
    showMsg(data.detail || "Timezone konnte nicht gespeichert werden.", 3000);
    return;
  }

  currentTimezone = timezone;
  showMsg("Timezone gespeichert.", 2000);
  await refreshStringsList();
});
function formatCreatedAt(value) {
  if (!value) return "";

  const d = new Date(value);

  return d.toLocaleString("de-DE", {
    timeZone: currentTimezone || "Europe/Berlin",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
}
function formatDateTimeWithSeconds(value) {
  if (!value) return "";

  const d = new Date(value);
  const tz = accountTimezone?.value || "Europe/Berlin";

  return d.toLocaleString("de-DE", {
    timeZone: tz,
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  });
}
// Thoughts
async function refreshStringsList() {
  const res = await fetch("/api/thoughts", { credentials: "include" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) return;

  stringsList.innerHTML = data.items.length
    ? `
      <div class="stringsListBox">
        ${data.items.map(t => {
          const parts = splitPrefixAndBody(t.content);
          return `
            <div
              class="ownStringItem"
              data-string-id="${t.id}"
            >
              <div class="stringItemDate">${escapeHtml(formatCreatedAt(t.created_at))}</div>
              <div class="stringItemContent">${escapeHtml(parts.body)}</div>
            </div>
          `;
        }).join("")}
      </div>
    `
    : "<p>Noch keine Einträge.</p>";
    document.querySelectorAll(".ownStringItem").forEach(el => {
      el.addEventListener("click", async () => {
        const thoughtId = el.dataset.stringId;

        window.history.pushState(
          {},
          "",
          `/${encodeURIComponent(currentUsername)}/${encodeURIComponent(thoughtId)}?from=overview`
        );

        await loadOwnThoughtDetail(thoughtId);
      });
    });
}
const stringCounter = document.getElementById("stringCounter");
const MAX_STRING_LENGTH = 500;

function updateStringCounter() {
  if (stringCounter) {
    stringCounter.textContent = `${stringInput.value.length} / ${MAX_STRING_LENGTH}`;
  }
}

stringInput.setAttribute("maxlength", String(MAX_STRING_LENGTH));
stringInput.addEventListener("input", updateStringCounter);
updateStringCounter();
stringInput.setAttribute("maxlength", String(MAX_STRING_LENGTH));

stringInput.addEventListener("input", () => {
  if (stringInput.value.length > MAX_STRING_LENGTH) {
    stringInput.value = stringInput.value.slice(0, MAX_STRING_LENGTH);
  }
});
function normalizeText(text) {
  return text
    .normalize("NFC")
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n");
}

saveBtn.addEventListener("click", async (e) => {
  e.preventDefault();
  if (isSaving) return;

  const content = normalizeText(stringInput.value);

  if (!content) {
    showMsg("Bitte einen String eingeben.", 3000);
    return;
  }

  if (content.length > MAX_STRING_LENGTH) {
    showMsg(`Maximal ${MAX_STRING_LENGTH} Zeichen erlaubt.`, 3000);
    return;
  }

  isSaving = true;
  saveBtn.disabled = true;
  setSaveBtnState("loading");

  try {
    const res = await fetch("/api/thoughts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ content })
    });

    const data = await res.json().catch(() => ({}));

    if (!res.ok) {
      setSaveBtnState("error");
      showMsg(data.detail || "Fehler beim Speichern.", 3000);

      setTimeout(() => {
        resetSaveButton();
      }, 900);
      return;
    }

    setSaveBtnState("success");
    showMsg(`Gespeichert: "${content}"`, 3000);
    stringInput.value = "";
    await refreshStringsList();

    setTimeout(() => {
      closePostModal();
    }, 900);

  } catch (err) {
    setSaveBtnState("error");
    showMsg("Fehler beim Speichern.", 3000);

    setTimeout(() => {
      resetSaveButton();
    }, 900);
  }
});

// Public search
async function runSearch() {
  const q = searchAccInput.value.trim();
  if (!q) {
    searchResults.innerHTML = "";
    searchResults.style.display = "none";
    publicStringsList.innerHTML = "";
    return;
  }

  const res = await fetch(`/api/public/search?q=${encodeURIComponent(q)}`);
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

  searchResults.innerHTML = data.items.map(u => `
    <button
      class="accItem"
      data-user-id="${u.id}"
      data-username="${u.username}"
      type="button"
    >
      ${escapeHtml(u.username)}
    </button>
  `).join("");

  searchResults.style.display = "block";

  document.querySelectorAll(".accItem").forEach(btn => {
    btn.addEventListener("click", () => {
      const username = btn.dataset.username;
      window.location.href = `/${encodeURIComponent(username)}`;
    });
  });
}

let searchDebounce;

searchAccInput.addEventListener("input", () => {
  clearTimeout(searchDebounce);
  searchDebounce = setTimeout(runSearch, 200);
});

document.addEventListener("click", (e) => {
  const clickedInsideSearch =
    e.target === searchAccInput ||
    e.target === searchAccBtn ||
    e.target.closest("#searchResults");

  if (!clickedInsideSearch) {
    searchResults.style.display = "none";
  }
});

async function loadPublicThoughtsByUsername(username) {
  const res = await fetch(`/api/public/user/${encodeURIComponent(username)}`);
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
            ${data.items.map(t => {
              const parts = splitPrefixAndBody(t.content);
              return `
                <div
                  class="stringItem"
                  data-string-id="${t.id}"
                  data-username="${data.user.username}"
                >
                  <div class="stringItemDate">${escapeHtml(formatCreatedAt(t.created_at))}</div>
                  <div class="stringItemContent">${escapeHtml(parts.body)}</div>
                </div>
              `;
            }).join("")}
          </div>
        `
        : "<p>No strings.</p>"
    }
  `;
}
function getFromQuery() {
  const params = new URLSearchParams(window.location.search);
  return params.get("from");
}
async function loadOwnThoughtDetail(thoughtId) {
  const res = await fetch(
    `/api/thoughts/${encodeURIComponent(thoughtId)}`,
    { credentials: "include" }
  );
  const data = await res.json().catch(() => ({}));

  showOnly(searchView);
  searchResults.innerHTML = "";

  const ownUsername = data.username || currentUsername || "";
  const from = getFromQuery();
  const backHref = from === "overview"
    ? "/?view=overview"
    : `/${encodeURIComponent(ownUsername)}`;

  if (!res.ok) {
    publicStringsList.innerHTML = `
      <div class="card">
        <p>Fehler: ${escapeHtml(data.detail || "String konnte nicht geladen werden.")}</p>
      </div>
    `;
    return;
  }

  const lines = String(data.content ?? "").trim().split("\n");
  const prefix = lines.slice(0, 2).join("\n").trim();
  const body = lines.slice(2).join("\n").trim();

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
          <div><span class="meta-label">blocktime</span><span class="meta-value">${escapeHtml(formatDateTimeWithSeconds(data.blocktime))}</span></div>    
          <div><span class="meta-label">hash</span><span class="meta-value">${escapeHtml(String(data.hashed_string ?? ""))}</span></div>
          <div><span class="meta-label">txid</span><span class="meta-value">${escapeHtml(String(data.txid ?? ""))}</span></div>
          ${data.etherscan_link ? `<div><span class="meta-label">link</span><a class="meta-value" href="${data.etherscan_link}" target="_blank" rel="noopener noreferrer">etherscan</a></div>` : ""}
        </div>
      </div>
    </div>
  `;

  const copyBtn = document.getElementById("copyLinkBtn");
  if (copyBtn) {
    copyBtn.addEventListener("click", async () => {
      try {
        const url = new URL(window.location.href);
        url.searchParams.delete("from");
        const cleanUrl = url.origin + url.pathname;
        await navigator.clipboard.writeText(cleanUrl);
        showMsg("Link copied!", 2000);
      } catch (err) {
        showMsg("Copy failed", 2000);
      }
    });
  }

  const proofHashBtn = document.getElementById("proofHashBtn");
  if (proofHashBtn) {
    proofHashBtn.addEventListener("click", () => {
      openProofHashModal(
`
INPUT
-----
text     = ${JSON.stringify(body)}
username = ${JSON.stringify(ownUsername)}
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
`
      );
    });
  }
}


async function loadPublicThoughtDetail(username, thoughtId) {
  const res = await fetch(
    `/api/public/user/${encodeURIComponent(username)}/thoughts/${encodeURIComponent(thoughtId)}`
  );
  const data = await res.json().catch(() => ({}));

  showOnly(searchView);
  searchResults.innerHTML = "";

  const from = getFromQuery();
  const backHref = from === "overview"
    ? "/?view=overview"
    : `/${encodeURIComponent(username)}`;

  if (!res.ok) {
    publicStringsList.innerHTML = `
      <div class ="card">
        <p>Fehler: ${escapeHtml(data.detail || "String konnte nicht geladen werden.")}</p>
      </div>
    `;

    const copyBtn = document.getElementById("copyLinkBtn");
    if (copyBtn) {
      copyBtn.addEventListener("click", async () => {
        try {
          const url = new URL(window.location.href);
          url.searchParams.delete("from");
          const cleanUrl = url.origin + url.pathname;

          await navigator.clipboard.writeText(cleanUrl);
          showMsg("Link copied!", 2000);
        } catch (err) {
          showMsg("Copy failed", 2000);
        }
      });
    }

    return;
  }

const etherscanHtml = data.etherscan_link
  ? `<a class="metaLink" href="${data.etherscan_link}" target="_blank" rel="noopener noreferrer">Etherscan öffnen</a>`
  : "";
const parts = splitPrefixAndBody(String(data.content ?? "").trim());
const lines = String(data.content ?? "").trim().split("\n");
const prefix = lines.slice(0, 2).join("\n").trim();
const body = lines.slice(2).join("\n").trim();

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


    //return `<span class="detail-prefix">${escapeHtml(prefix).replace(/\n/g, "<br>")}</span><br><span class="detail-body">${escapeHtml(body).replace(/\n/g, "<br>")}</span>`;
    return `<span class="detail-prefix">${escapeHtml(prefix).replace(/\n/g, "<br>")}</span><br><br><span class="detail-body">${escapeHtml(body).replace(/\n/g, "<br>")}</span>`;
    })()}</div>

      <div class="detail-meta">
        <div><span class="meta-label">blocktime</span><span class="meta-value">${escapeHtml(formatDateTimeWithSeconds(data.blocktime))}</span></div>        <div><span class="meta-label">hash</span><span class="meta-value">${escapeHtml(String(data.hashed_string ?? ""))}</span></div>
        <div><span class="meta-label">txid</span><span class="meta-value">${escapeHtml(String(data.txid ?? ""))}</span></div>
        ${data.etherscan_link ? `<div><span class="meta-label">link</span><a class="meta-value" href="${data.etherscan_link}" target="_blank" rel="noopener noreferrer">etherscan</a></div>` : ""}
      </div>
    </div>
  </div>
`;

  const copyBtn = document.getElementById("copyLinkBtn");
  if (copyBtn) {
    copyBtn.addEventListener("click", async () => {
      try {
        const url = new URL(window.location.href);
        url.searchParams.delete("from");
        const cleanUrl = url.origin + url.pathname;

        await navigator.clipboard.writeText(cleanUrl);
        showMsg("Link copied!", 2000);
      } catch (err) {
        showMsg("Copy failed", 2000);
      }
    });
  }
  const proofHashBtn = document.getElementById("proofHashBtn");
  if (proofHashBtn) {
    proofHashBtn.addEventListener("click", () => {
      openProofHashModal(
    `
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
`
      );
    });
  }


}
const closeProofHashModalBtn = document.getElementById("closeProofHashModalBtn");
  if (closeProofHashModalBtn) {
    closeProofHashModalBtn.addEventListener("click", () => {
      closeProofHashModal();
    });
  }
  
searchAccInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") runSearch();
});

publicStringsList.addEventListener("click", (e) => {
  const item = e.target.closest(".stringItem");
  if (!item) return;

  const stringId = item.dataset.stringId;
  const username = item.dataset.username;
  window.location.href = `/${encodeURIComponent(username)}/${encodeURIComponent(stringId)}`;
});

stringsList.addEventListener("click", async (e) => {
  const item = e.target.closest(".ownStringItem");
  if (!item) return;

  let username = currentUsername;

  if (!username) {
    const ok = await loadAccount();
    if (!ok || !currentUsername) {
      showMsg("Username konnte nicht geladen werden.", 3000);
      return;
    }
    username = currentUsername;
  }

  const stringId = item.dataset.stringId;
  window.location.href = `/${encodeURIComponent(username)}/${encodeURIComponent(stringId)}?from=overview`;
});

function getViewFromQuery() {
  const params = new URLSearchParams(window.location.search);
  return params.get("view");
}

let typingTimeout = null;
let typingLoopActive = false;

function stopTypingLoop() {
  typingLoopActive = false;

  if (typingTimeout) {
    clearTimeout(typingTimeout);
    typingTimeout = null;
  }
}

function startTypingWords(element, words, speed = 50, pauseAfterWord = 10000) {
  if (!element || !Array.isArray(words) || words.length === 0) return;

  stopTypingLoop();
  typingLoopActive = true;

  let wordIndex = 0;

  function typeWord() {
    if (!typingLoopActive) return;

    const entry = words[wordIndex];
    const text = typeof entry === "string" ? entry : entry.text;
    const className = typeof entry === "string" ? "" : (entry.className || "");

    let charIndex = 0;
    element.textContent = "";
    element.className = className;

    function step() {
      if (!typingLoopActive) return;

      element.textContent = text.slice(0, charIndex);
      charIndex += 1;

      if (charIndex <= text.length) {
        typingTimeout = setTimeout(step, speed);
      } else {
        typingTimeout = setTimeout(() => {
          if (!typingLoopActive) return;
          wordIndex = (wordIndex + 1) % words.length;
          typeWord();
        }, pauseAfterWord);
      }
    }

    step();
  }

  typeWord();
}

function splitPrefixAndBody(text) {
  const value = String(text ?? "").trim();
  const lines = value.split("\n");

  if (lines.length <= 2) {
    return {
      prefix: value,
      body: ""
    };
  }

  return {
    prefix: lines.slice(0, 2).join("\n"),
    body: lines.slice(2).join("\n")
  };
}
function nl2brEscaped(text) {
  return escapeHtml(String(text ?? "")).replace(/\n/g, "<br>");
}


// init
async function initApp() {
  await refreshAuthUI();
  const queryView = getViewFromQuery();
  const route = parseRoute();
  const loggedIn = await isLoggedIn();

  if (route.type === "settings") {
    if (!loggedIn) {
      setHomeButtonDisabled(true);
      showOnly(homeView);
      return;
    }

    setHomeButtonDisabled(false);

    const ok = await loadAccount();
    if (!ok) return;

    showOnly(accountView);
    return;
  }

  if (route.type === "thought") {
    if (loggedIn && !currentUsername) {
      const ok = await loadAccount();
      if (!ok) return;
    }

    if (
      loggedIn &&
      currentUsername &&
      route.username &&
      route.username.toLowerCase() === currentUsername.toLowerCase()
    ) {
      await loadOwnThoughtDetail(route.thoughtId);
    } else {
      await loadPublicThoughtDetail(route.username, route.thoughtId);
    }
    return;
  }

  if (route.type === "user") {
    setHomeButtonDisabled(false);
    await loadPublicThoughtsByUsername(route.username);
    return;
  }

  if (queryView === "overview" && loggedIn) {
    const ok = await loadAccount();
    if (!ok) return;

    setHomeButtonDisabled(true);
    showOnly(overviewView);
    await refreshStringsList();
    return;
  }

  if (loggedIn) {
    const ok = await loadAccount();
    if (!ok) return;

    setHomeButtonDisabled(true);
    showOnly(overviewView);
    await refreshStringsList();
    return;
  }

  setHomeButtonDisabled(true);
  showOnly(homeView);
}

initApp();
