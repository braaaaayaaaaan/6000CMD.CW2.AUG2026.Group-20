import axios from "axios";
import { currentSession, setSession } from "./session";

// Match the page hostname for host-only SameSite cookies (localhost vs 127.0.0.1).
export const API_BASE_URL = (process.env.NEXT_PUBLIC_API_URL ||
  (typeof window !== "undefined" ? window.location.protocol + "//" + window.location.hostname + ":8000" : "http://127.0.0.1:8000")).replace(/\/+$/, "");
export const api = axios.create({ baseURL: API_BASE_URL, withCredentials: true, timeout: 30000 });
let csrfToken = "";
let csrfPending = null;
let refreshing = null;
let restoring = null;

export function clearSession() {
  setSession(null, true);
}

async function ensureCsrf(force = false) {
  if (force) csrfToken = "";
  if (csrfToken) return csrfToken;
  if (!csrfPending) csrfPending = axios.get(API_BASE_URL + "/api/account/csrf/", { withCredentials: true, timeout: 15000 })
    .then(({ data }) => { csrfToken = data.csrfToken; return csrfToken; })
    .finally(() => { csrfPending = null; });
  return csrfPending;
}

function publicRequest(config) {
  const path = new URL(config.url, API_BASE_URL + "/").pathname;
  return path.startsWith("/api/token/") || path.startsWith("/api/account/mfa/") ||
    ["/api/account/csrf/", "/api/account/verify-email/", "/api/account/resend-verification/",
      "/api/account/forgot-password/", "/api/account/reset-password/", "/api/logout/", "/api/logout-all/"].includes(path) ||
    (path === "/users/" && config.method === "post");
}

api.interceptors.request.use(async (config) => {
  if (new URL(config.url, API_BASE_URL + "/").origin !== new URL(API_BASE_URL).origin) {
    throw new Error("The API returned an unexpected address.");
  }
  delete config.headers.Authorization;
  if (!["get", "head", "options"].includes(config.method)) config.headers["X-CSRFToken"] = await ensureCsrf();
  config.sessionUser ??= currentSession().id;
  return config;
});

api.interceptors.response.use((response) => {
  if (response.data?.csrfToken) csrfToken = response.data.csrfToken;
  return response;
}, async (error) => {
  const config = error.config;
  if (!config || typeof window === "undefined") throw error;
  if (error.response?.status === 403 && String(error.response.data?.detail).startsWith("CSRF Failed") && !config.csrfRetried) {
    config.csrfRetried = true;
    await ensureCsrf(true);
    return api(config);
  }
  if (error.response?.status !== 401 || publicRequest(config)) throw error;
  if (config.sessionUser !== currentSession().id) throw new axios.CanceledError("Session changed.");
  if (config.sessionRetried) { clearSession(); throw error; }
  config.sessionRetried = true;
  if (!refreshing) {
    const rotate = async () => {
      if (config.sessionUser !== currentSession().id) throw new axios.CanceledError("Session changed.");
      const { data } = await api.post("/api/token/refresh/");
      setSession(data.user);
    };
    refreshing = (globalThis.navigator?.locks?.request ? navigator.locks.request("dam-token-refresh", rotate) : rotate())
      .catch((refreshError) => { if (refreshError.response?.status === 401) clearSession(); throw refreshError; })
      .finally(() => { refreshing = null; });
  }
  await refreshing;
  return api(config);
});

export function restoreSession(force = false) {
  if (typeof window === "undefined") return Promise.resolve();
  if (!force && currentSession().ready) return Promise.resolve();
  if (!restoring) {
    // Remove credentials left by the previous localStorage implementation.
    try { for (const key of ["accessToken", "refreshToken", "username", "id", "group"]) localStorage.removeItem(key); } catch { /* storage may be disabled */ }
    restoring = api.get("/api/account/me/")
      .then(({ data }) => setSession(data.user))
      .catch(() => setSession(null))
      .finally(() => { restoring = null; });
  }
  return restoring;
}

export async function downloadAsset(asset, filename) {
  const { data } = await api.get("/assets/" + asset.id + "/media-url/");
  const link = document.createElement("a");
  const url = new URL(data.url, API_BASE_URL + "/");
  url.searchParams.set("download", "1");
  link.href = url.href;
  link.referrerPolicy = "no-referrer";
  link.download = filename || asset.name + "." + asset.file_type;
  document.body.appendChild(link);
  link.click();
  link.remove();
}

export function mediaUrl(value) {
  return value ? new URL(value, API_BASE_URL + "/").href : "";
}

export function errorMessage(error, fallback = "Unable to complete this request. Please try again.") {
  function messages(value) {
    if (Array.isArray(value)) return value.flatMap(messages);
    if (value && typeof value === "object") {
      return Object.entries(value).flatMap(([field, detail]) =>
        messages(detail).map((message) => field === "detail" || field === "non_field_errors"
          ? message : field.replaceAll("_", " ") + ": " + message));
    }
    return typeof value === "string" ? [value] : [];
  }
  const data = error.response?.data;
  if (data && typeof data === "object") return messages(data).join(" ") || fallback;
  return error.response || error.code ? fallback : error.message || fallback;
}

export async function getAllPages(path, { signal } = {}) {
  const rows = [];
  const visited = new Set();
  let next = path;
  while (next) {
    if (visited.has(next)) throw new Error("Unable to finish loading the list.");
    visited.add(next);
    const { data } = await api.get(next, { signal });
    rows.push(...(Array.isArray(data) ? data : data.results));
    next = Array.isArray(data) ? null : data.next;
  }
  return rows;
}
