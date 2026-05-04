import { apiFetch } from "./api.js";
import { state } from "./state.js";
import {
  accountEmail,
  accountUsernameEl,
  publicStringsChk,
  saveEmailBtn,
  cancelEmailBtn,
  oldPw,
  newPw,
  newPw2,
  saveVisibilityBtn,
  savePwBtn,
  accountTimezone,
  saveTimezoneBtn,
} from "./dom.js";
import { showMsg } from "./ui.js";

export async function loadAccount() {
  try {
    const data = await apiFetch("/api/account");

    state.originalEmail = data.email;
    state.currentUsername = data.username;
    state.currentTimezone = data.timezone || "Europe/Berlin";

    if (accountEmail) accountEmail.value = data.email;
    if (publicStringsChk) publicStringsChk.checked = !!data.strings_public;
    if (accountTimezone) accountTimezone.value = state.currentTimezone;
    if (accountUsernameEl) accountUsernameEl.textContent = `@${data.username}`;

    return true;
  } catch (err) {
    showMsg(err.message || "Account konnte nicht geladen werden.", 3000);
    return false;
  }
}

export function setEmailEditMode(on) {
  if (!accountEmail || !saveEmailBtn || !cancelEmailBtn) return;

  accountEmail.readOnly = !on;
  saveEmailBtn.style.display = on ? "inline-block" : "none";
  cancelEmailBtn.style.display = on ? "inline-block" : "none";
  if (on) accountEmail.focus();
}

export function initAccountEvents() {
  accountEmail?.addEventListener("dblclick", () => setEmailEditMode(true));

  cancelEmailBtn?.addEventListener("click", () => {
    accountEmail.value = state.originalEmail;
    setEmailEditMode(false);
  });

  saveEmailBtn?.addEventListener("click", async () => {
    const email = accountEmail.value.trim();

    try {
      await apiFetch("/api/account/request-email-change", {
        method: "PUT",
        body: JSON.stringify({ email }),
      });

      setEmailEditMode(false);
      showMsg("Bestätigungslink wurde an die neue Email gesendet. Bitte verifizieren.", 5000);
    } catch (err) {
      showMsg(err.status === 409 ? "Email existiert bereits." : err.message || "Email konnte nicht geändert werden.", 3000);
    }
  });

  saveVisibilityBtn?.addEventListener("click", async () => {
    try {
      const data = await apiFetch("/api/account/visibility", {
        method: "PUT",
        body: JSON.stringify({ strings_public: publicStringsChk.checked }),
      });

      showMsg(data.strings_public ? "Strings sind jetzt public." : "Strings sind jetzt private.", 3000);
    } catch (err) {
      showMsg(err.message || "Konnte nicht speichern.", 3000);
    }
  });

  savePwBtn?.addEventListener("click", async () => {
    const payload = {
      old_password: oldPw.value,
      new_password: newPw.value,
      new_password2: newPw2.value,
    };

    try {
      await apiFetch("/api/account/password", {
        method: "PUT",
        body: JSON.stringify(payload),
      });

      oldPw.value = "";
      newPw.value = "";
      newPw2.value = "";
      showMsg("Passwort geändert.", 3000);
    } catch (err) {
      showMsg(err.message || "Passwort konnte nicht geändert werden.", 3000);
    }
  });

  saveTimezoneBtn?.addEventListener("click", async () => {
    const timezone = accountTimezone.value;

    try {
      await apiFetch("/api/account/timezone", {
        method: "POST",
        body: JSON.stringify({ timezone }),
      });

      state.currentTimezone = timezone;
      showMsg("Timezone gespeichert.", 2000);
    } catch (err) {
      showMsg(err.message || "Timezone konnte nicht gespeichert werden.", 3000);
    }
  });
}
