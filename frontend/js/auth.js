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
let turnstileToken = "";
let turnstileWidgetId = null;

function renderSignupTurnstile() {
  if (!window.turnstile) return;
  if (turnstileWidgetId !== null) return;

  const el = document.getElementById("signupTurnstile");
  if (!el) return;

  turnstileWidgetId = window.turnstile.render(el, {
    sitekey: "0x4AAAAAADKXaymjn1wmLr6A",
    theme: "light",

    callback(token) {
      turnstileToken = token;
    },

    "expired-callback"() {
      turnstileToken = "";
    },

    "error-callback"() {
      turnstileToken = "";
    },
  });
}

window.addEventListener("turnstile-ready", renderSignupTurnstile);

if (window.turnstile) {
  renderSignupTurnstile();
}
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
    turnstileToken = "";

      if (window.turnstile && turnstileWidgetId !== null) {
        window.turnstile.reset(turnstileWidgetId);
      } else {
	  renderSignupTurnstile();
	}
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
      showMsg("Logged in.", 2000);
      window.location.href = "/";
    } catch (err) {
      state.failedLocal += 1;

      if (err.status === 423) {
        lockLoginUI(true);
        showMsg(err.message || "Too many failed attempts. Reset required.", 5000);
        return;
      }

      showMsg(err.message || "Login failed", 3000);
      if (state.failedLocal >= 5 && resetPwBtn) resetPwBtn.style.display = "inline-block";
    }

  });

  resetPwBtn?.addEventListener("click", async () => {
    const email = loginInput.value.trim();

    if (!email) {
      showMsg("Please enter your email address.", 3000);
      return;
    }

    await apiRaw("/api/password-reset/request", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });

    showMsg("If a reset is possible, an email has been sent.", 5000);
  });

  signupBtn?.addEventListener("click", async () => {
    const email = signupEmailInput.value.trim();
    const username = signupUsernameInput.value.trim();
    const password = signupPasswordInput.value;
    if (!turnstileToken) {
      showMsg("Bitte bestätige die Sicherheitsprüfung.", 2500);
      return;
    }
    try {
      const data = await apiFetch("/api/signup", {
        method: "POST",
        body: JSON.stringify({ email, username, password,turnstile_token: turnstileToken  }),
      });

      showMsg(data.message || "Please verify your email address.", 5000);
      showOnly(loginView);
    } catch (err) {
      if (err.status === 409) {
        showMsg(err.message || "This email address or username is already taken.", 3000);
      } else {
        showMsg(err.message || "Error during creation.", 3000);
      }
    }
	finally {
	if (window.turnstile && turnstileWidgetId !== null) {
	  window.turnstile.reset(turnstileWidgetId);
	}

	turnstileToken = "";
	  }
  });

  logoutBtn?.addEventListener("click", async () => {
    await apiRaw("/api/logout", { method: "POST", credentials: "include" });
    showMsg("Logged out.", 3000);
    await refreshAuthUI();
    window.location.href = "/";
  });
}
