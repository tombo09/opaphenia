export function parseRoute() {
  const parts = window.location.pathname
    .replace(/^\/+|\/+$/g, "")
    .split("/")
    .filter(Boolean);

  if (parts.length === 0) return { type: "home" };

  if (parts[0] === "index.html" || parts[0] === "subpage.html") {
    return { type: "home" };
  }

  if (parts.length === 1 && parts[0] === "settings") {
    return { type: "settings" };
  }

  if (parts.length === 3 && parts[0] === "own" && parts[1] === "thoughts") {
    return { type: "own-thought", thoughtId: decodeURIComponent(parts[2]) };
  }

  if (parts.length === 1) {
    return { type: "user", username: decodeURIComponent(parts[0]) };
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
