import {
  homeBtn,
  accountBtn,
  overviewBtn,
  loginInput,
  loginPasswordInput,
  loginView,
  overviewView,
  accountView,
  searchView,
  homeView,
  openPostModalBtn,
  closePostModalBtn,
  postModalOverlay,
  proofHashModal,
  closeProofHashModalBtn,
} from "./dom.js";

import { state } from "./state.js";
import { parseRoute } from "./router.js";
import { getViewFromQuery } from "./utils.js";
import {
  showOnly,
  showMsg,
  setHomeButtonDisabled,
  openPostModal,
  closePostModal,
  closeProofHashModal,
} from "./ui.js";

import { isLoggedIn, refreshAuthUI, initAuthEvents } from "./auth.js";
import { loadAccount, initAccountEvents } from "./account.js";
import { refreshStringsList, loadOwnThoughtDetail, initThoughtEvents } from "./thoughts.js";
import {
  loadPublicThoughtsByUsername,
  loadPublicThoughtDetail,
  initPublicEvents,
} from "./public.js";

function initGlobalEvents() {
  homeBtn?.addEventListener("click", async () => {
    history.pushState({}, "", "/");

    if (await isLoggedIn()) {
      showOnly(overviewView);
      await refreshStringsList();
    } else {
      showOnly(homeView);
    }
  });

  accountBtn?.addEventListener("click", async () => {
    if (await isLoggedIn()) {
      history.pushState({}, "", "/settings");
      await initApp();
    } else {
      setHomeButtonDisabled(false);
      showOnly(loginView);
      if (loginInput) loginInput.value = "";
      if (loginPasswordInput) loginPasswordInput.value = "";
    }
  });

  overviewBtn?.addEventListener("click", async () => {
    if (!(await isLoggedIn())) {
      showOnly(loginView);
      return;
    }

    showOnly(overviewView);
    await refreshStringsList();
  });

  window.addEventListener("popstate", () => {
    initApp();
  });

  openPostModalBtn?.addEventListener("click", openPostModal);
  closePostModalBtn?.addEventListener("click", closePostModal);

  postModalOverlay?.addEventListener("click", (e) => {
    if (e.target === postModalOverlay) closePostModal();
  });

  proofHashModal?.addEventListener("click", (e) => {
    if (e.target === proofHashModal) closeProofHashModal();
  });

  closeProofHashModalBtn?.addEventListener("click", closeProofHashModal);
}

export async function initApp() {
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
    if (loggedIn && !state.currentUsername) {
      const ok = await loadAccount();
      if (!ok) return;
    }

    if (
      loggedIn &&
      state.currentUsername &&
      route.username &&
      route.username.toLowerCase() === state.currentUsername.toLowerCase()
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

initGlobalEvents();
initAuthEvents();
initAccountEvents();
initThoughtEvents();
initPublicEvents();

initApp().catch((err) => {
  console.error(err);
  showMsg("App konnte nicht geladen werden.", 3000);
});
