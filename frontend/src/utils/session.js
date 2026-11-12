// Only non-secret profile data lives in memory. Credentials remain HttpOnly.
let snapshot = JSON.stringify({ ready: false, authenticated: false, username: "", id: "", group: "" });
const listeners = new Set();
let channel;

// Keep the resend address within this browser tab; never store passwords or tokens.
let verificationEmail = "";
export function rememberVerificationEmail(email = "") {
  verificationEmail = email;
  try {
    if (email) window.sessionStorage.setItem("dam-verification-email", email);
    else window.sessionStorage.removeItem("dam-verification-email");
  } catch { /* The in-memory address still works when storage is unavailable. */ }
}

export function getVerificationEmail() {
  try {
    return window.sessionStorage.getItem("dam-verification-email") || verificationEmail;
  } catch {
    return verificationEmail;
  }
}

export const getSessionSnapshot = () => snapshot;
export const getServerSnapshot = () => null;
export const currentSession = () => JSON.parse(snapshot);

export function setSession(user, broadcast = false) {
  const next = JSON.stringify({ ready: true, authenticated: Boolean(user), username: "", id: "", group: "", ...user });
  if (snapshot !== next) {
    snapshot = next;
    listeners.forEach((listener) => listener());
  }
  if (broadcast) channel?.postMessage(user ? "changed" : "logout");
}

export function subscribeSession(listener) {
  if (typeof window !== "undefined" && !channel && typeof BroadcastChannel !== "undefined") {
    channel = new BroadcastChannel("dam-account");
    channel.onmessage = ({ data }) => {
      if (data === "logout") setSession(null);
      else window.dispatchEvent(new Event("dam-auth-refresh"));
    };
  }
  listeners.add(listener);
  return () => listeners.delete(listener);
}
