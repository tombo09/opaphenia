import { apiFetch, apiRaw } from "./api.js";
import { state } from "./state.js";
import {
  logoutBtn,
  overviewBtn,
  loginInput,
  loginPasswordInput,
  loginBtn,
  resetPwBtn,
  signupEmailInput,
  signupUsernameInput,
  signupPasswordInput,
  signupBtn,
  openSignupBtn,
  backToLoginBtn,
  signupView,
  loginView,
} from "./dom.js";
import { showMsg, showOnly } from "./ui.js";

export async function isLoggedIn() {
  try {
    const res = await apiRaw("/api/me", { credentials: "include" });
    return res.ok;
  } catch {
    return false;
  }
}

export async function refreshAuthUI() {
  const ok = await isLoggedIn();
  if (logoutBtn) logoutBtn.style.display = ok ? "inline-block" : "none";
  if (overviewBtn) overviewBtn.style.display = "none";
}

function lockLoginUI(locked) {
  if (loginPasswordInput) loginPasswordInput.disabled = locked;
  if (loginBtn) loginBtn.disabled = locked;
  if (resetPwBtn) resetPwBtn.style.display = locked ? "inline-block" : "none";
}

export function initAuthEvents() {
  openSignupBtn?.addEventListener("click", () => {
    showOnly(signupView);
    if (signupEmailInput) signupEmailInput.value = "";
    if (signupUsernameInput) signupUsernameInput.value = "";
    if (signupPasswordInput) signupPasswordInput.value = "";
  });

  backToLoginBtn?.addEventListener("click", () => {
    showOnly(loginView);
  });

  loginBtn?.addEventListener("click", async () => {
    const login = loginInput.value.trim();
    const password = loginPasswordInput.value;

    try {
      await apiFetch("/api/login", {
        method: "POST",
        body: JSON.stringify({ login, password }),
      });

      state.failedLocal = 0;
      lockLoginUI(false);
      loginInput.value = "";
      loginPasswordInput.value = "";
      showMsg("Eingeloggt.", 2000);
      window.location.href = "/";
    } catch (err) {
      state.failedLocal += 1;

      if (err.status === 423) {
        lockLoginUI(true);
        showMsg(err.message || "Zu viele Fehlversuche. Reset nötig.", 5000);
        return;
      }

      showMsg(err.message || "Login fehlgeschlagen", 3000);
      if (state.failedLocal >= 5 && resetPwBtn) resetPwBtn.style.display = "inline-block";
    }
  });

  resetPwBtn?.addEventListener("click", async () => {
    const email = loginInput.value.trim();

    if (!email) {
      showMsg("Bitte Email eingeben.", 3000);
      return;
    }

    await apiRaw("/api/password-reset/request", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });

    showMsg("Wenn ein Reset möglich ist, wurde eine Email gesendet.", 5000);
  });

  signupBtn?.addEventListener("click", async () => {
    const email = signupEmailInput.value.trim();
    const username = signupUsernameInput.value.trim();
    const password = signupPasswordInput.value;

    try {
      const data = await apiFetch("/api/signup", {
        method: "POST",
        body: JSON.stringify({ email, username, password }),
      });

      showMsg(data.message || "Bitte Email verifizieren.", 5000);
      showOnly(loginView);
    } catch (err) {
      if (err.status === 409) {
        showMsg(err.message || "Email oder Username ist bereits vergeben.", 3000);
      } else {
        showMsg(err.message || "Fehler beim Erstellen.", 3000);
      }
    }
  });

  logoutBtn?.addEventListener("click", async () => {
    await apiRaw("/api/logout", { method: "POST", credentials: "include" });
    showMsg("Ausgeloggt.", 3000);
    await refreshAuthUI();
    window.location.href = "/";
  });
}
