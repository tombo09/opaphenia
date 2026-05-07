import {
  msg,
  views,
  homeBtn,
  accountBtn,
  homeView,
  loginView,
  signupView,
  overviewView,
  accountView,
  postModalOverlay,
  stringInput,
  saveBtn,
  proofHashModal,
  proofHashCodeBox,
} from "./dom.js";
import { state } from "./state.js";
import { startTypingWords, stopTypingLoop } from "./typing.js";

let msgTimer = null;
let msgClearTimer = null;

export function showMsg(text, ms = 5000) {
  if (!msg) return;

  if (msgTimer) clearTimeout(msgTimer);
  if (msgClearTimer) clearTimeout(msgClearTimer);

  msg.textContent = text;
  msg.classList.add("show");

  if (!ms) return;

  msgTimer = setTimeout(() => {
    msg.classList.remove("show");

    msgClearTimer = setTimeout(() => {
      if (!msg.classList.contains("show")) msg.textContent = "";
    }, 200);
  }, ms);
}

export function setHomeButtonDisabled(disabled) {
  if (homeBtn) homeBtn.disabled = disabled;
}

export function setAccountButtonDisabled(disabled) {
  if (accountBtn) accountBtn.disabled = disabled;
}

export function showOnly(viewEl) {
  views.forEach((v) => {
    v.style.display = "none";
  });

  if (!viewEl) return;

  if (viewEl === loginView || viewEl === signupView || viewEl === accountView) {
    viewEl.style.display = "flex";
  } else {
    viewEl.style.display = "block";
  }

  const typingTitle = document.getElementById("typingTitle");
  const thoughtUserMock = document.getElementById("thoughtUserMock");
  if (viewEl === homeView) {
    startTypingWords(
      typingTitle,
      [
        { username: "@tombo09, 30.06.2012 08:29:56",
          text: "If this page is forced to disappear your strings/words/work remain",
          className: "typingPos1",
        },
        { username: "@lisa, 1.01.2025 19:06:39",
          text: "this is not for fast pace typing aka doing writing mistakes i want to change it after few seconds environment",
          className: "typingPos2",
        },
        { username: "@testor",
          text: "this project runs as long some people believe in it ",
          className: "typingPos3",
        },
      ],
      80,
      3000, thoughtUserMock
    );
  } else {
    stopTypingLoop();
    if (typingTitle) typingTitle.textContent = "";
  }

  setHomeButtonDisabled(viewEl === overviewView || viewEl === homeView);
  setAccountButtonDisabled(viewEl === accountView);
}

export function setSaveBtnState(stateName) {
  if (!saveBtn) return;
  saveBtn.classList.remove("loading", "success", "error");
  if (stateName) saveBtn.classList.add(stateName);
}

export function resetSaveButton() {
  state.isSaving = false;
  if (saveBtn) saveBtn.disabled = false;
  setSaveBtnState(null);
}

export function openPostModal() {
  if (!postModalOverlay || !stringInput) return;

  resetSaveButton();
  postModalOverlay.style.display = "flex";

  requestAnimationFrame(() => {
    stringInput.focus();
    stringInput.setSelectionRange(stringInput.value.length, stringInput.value.length);
  });
}

export function closePostModal() {
  if (!postModalOverlay) return;
  resetSaveButton();
  postModalOverlay.style.display = "none";
}

export function openProofHashModal(content) {
  if (!proofHashModal || !proofHashCodeBox) return;
  proofHashCodeBox.textContent = content;
  proofHashModal.style.display = "flex";
}

export function closeProofHashModal() {
  if (!proofHashModal) return;
  proofHashModal.style.display = "none";
}



const proofFlipBox = document.querySelector(".proofFlipBox");

if (proofFlipBox) {
  proofFlipBox.addEventListener("click", () => {
    proofFlipBox.classList.toggle("isFlipped");
  });
}
