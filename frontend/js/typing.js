let typingTimeout = null;
let typingLoopActive = false;

export function stopTypingLoop() { typingLoopActive = false; if (typingTimeout) { clearTimeout(typingTimeout); typingTimeout = null; } }


export function startTypingWords(
  element,
  words,
  speed = 50,
  pauseAfterWord = 10000,
  usernameElement = null
) {
  if (!element || !Array.isArray(words) || words.length === 0) return;

  stopTypingLoop();
  typingLoopActive = true;

  let wordIndex = 0;

  function typeWord() {
    if (!typingLoopActive) return;

    const entry = words[wordIndex];

    const text = typeof entry === "string" ? entry : entry.text;
    const className = typeof entry === "string" ? "" : entry.className || "";
    const username = typeof entry === "string" ? "" : entry.username || "";

    let charIndex = 0;

    element.textContent = "";
    element.className = `thoughtTextareaMock ${className}`.trim();
    if (usernameElement) {
      usernameElement.textContent = username;
    }

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
