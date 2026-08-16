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
  walletDrawer,
  walletDrawerToggle,
  walletBalance,
  walletStrings,
  walletAddress,
  walletEtherscan,
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

let walletLoaded = false;


function showWalletDrawer() {
  walletDrawer?.classList.remove("hidden");
}


function hideWalletDrawer() {
  walletDrawer?.classList.add("hidden");
  walletDrawer?.classList.remove("open");
}


async function loadEthStatus() {
  try {
    const response = await fetch("/api/eth/status");

    if (!response.ok) {
      throw new Error("Could not load ETH status");
    }

    const data = await response.json();
const address = data.wallet_address;



walletAddress.textContent = address;

walletEtherscan.href =
  `https://etherscan.io/address/${address}`;
    walletBalance.textContent =
      `${Number(data.balance_eth).toFixed(5)} ETH`;

    walletStrings.textContent =
      Math.floor(data.possible_strings).toLocaleString();

  } catch (err) {
    console.error("ETH status:", err);

    walletBalance.textContent = "Unavailable";
    walletStrings.textContent = "—";
  }
}


function initGlobalEvents() {
  walletDrawerToggle?.addEventListener("click", async () => {
    walletDrawer.classList.toggle("open");

    if (
      walletDrawer.classList.contains("open") &&
      !walletLoaded
    ) {
      await loadEthStatus();
      walletLoaded = true;
    }
  });
  homeBtn?.addEventListener("click", async () => {
    history.pushState({}, "", "/");

    if (await isLoggedIn()) {
      hideWalletDrawer();
      const ok = await loadAccount();
      showOnly(overviewView);
      await refreshStringsList();
    } else {
      showOnly(homeView);
      showWalletDrawer();
    }
  });

  accountBtn?.addEventListener("click", async () => {
    hideWalletDrawer();
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
  hideWalletDrawer();
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
  showWalletDrawer();
}

initGlobalEvents();
initAuthEvents();
initAccountEvents();
initThoughtEvents();
initPublicEvents();

initApp().catch((err) => {
  console.error(err);
  showMsg("The app could not be loaded.", 3000);
});





