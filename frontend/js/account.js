import { apiFetch } from "./api.js";
import { state } from "./state.js";
import {
  accountEmail,
  emailChangeCurrentPassword,
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
    showMsg(err.message || "The account could not be loaded.", 3000);
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
        body: JSON.stringify({
          email,
          current_password: emailChangeCurrentPassword.value,
        }),
      });

      emailChangeCurrentPassword.value = "";
      setEmailEditMode(false);
      showMsg("A confirmation link has been sent to your new email address. Please verify it.", 5000);
    } catch (err) {
      showMsg(err.status === 409 ? "This email address already exists" : err.message || "The email address could not be changed.", 3000);
    }
  });

  saveVisibilityBtn?.addEventListener("click", async () => {
    try {
      const data = await apiFetch("/api/account/visibility", {
        method: "PUT",
        body: JSON.stringify({ strings_public: publicStringsChk.checked }),
      });

      showMsg(data.strings_public ? "Strings are now public." : "Strings are now private.", 3000);
    } catch (err) {
      showMsg(err.message || "Unable to save.", 3000);
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
      showMsg("Password changed.", 3000);
    } catch (err) {
      showMsg(err.message || "The password could not be changed.", 3000);
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
      showMsg("Time zone saved", 2000);
    } catch (err) {
      showMsg(err.message || "The time zone could not be saved", 3000);
    }
  });
}


const exportStringsBtn = document.getElementById("exportStringsBtn");

if (exportStringsBtn) {
  exportStringsBtn.addEventListener("click", async () => {
    try {
      exportStringsBtn.disabled = true;
      exportStringsBtn.textContent = "Exporting...";

      const res = await fetch("/api/account/export", {
        method: "GET",
        credentials: "include"
      });

      if (!res.ok) {
        throw new Error("Export failed");
      }

      const blob = await res.blob();

      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");

      a.href = url;
      a.download = "strings-export.json";
      document.body.appendChild(a);
      a.click();

      a.remove();
      URL.revokeObjectURL(url);

      showMsg("Export downloaded", 2000);
    } catch (err) {
      console.error(err);
      showMsg("Export failed", 2500);
    } finally {
      exportStringsBtn.disabled = false;
      exportStringsBtn.textContent = "Strings als JSON exportieren";
    }
  });
}
