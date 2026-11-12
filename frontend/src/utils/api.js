import axios from "axios";

export const API_BASE_URL = (process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
export const api = axios.create({ baseURL: API_BASE_URL });

export function clearSession() {
  for (const key of ["accessToken", "refreshToken", "username", "id", "group"]) localStorage.removeItem(key);
  window.dispatchEvent(new Event("dam-session-change"));
}

let refreshing = null;
function isPublicRequest(config) {
  const path = new URL(config.url, API_BASE_URL + "/").pathname;
  return path.startsWith("/api/token/") || (path === "/users/" && config.method === "post");
}

api.interceptors.request.use((config) => {
  if (new URL(config.url, API_BASE_URL + "/").origin !== new URL(API_BASE_URL).origin) {
    throw new Error("The API returned an unexpected address.");
  }
  if (typeof window !== "undefined" && !isPublicRequest(config)) {
    config.sessionUser ??= localStorage.getItem("id");
    const token = localStorage.getItem("accessToken");
    if (token) config.headers.Authorization = "Bearer " + token;
    else delete config.headers.Authorization;
  }
  return config;
});

api.interceptors.response.use((response) => response, async (error) => {
  const config = error.config;
  if (typeof window === "undefined" || error.response?.status !== 401 || !config || isPublicRequest(config)) throw error;
  if (config.sessionUser !== localStorage.getItem("id")) throw new axios.CanceledError("Session changed.");
  const refreshToken = localStorage.getItem("refreshToken");
  if (config.sessionRetried || !refreshToken) {
    clearSession();
    throw error;
  }
  config.sessionRetried = true;
  // Another request may already have refreshed the access token.
  if (config.headers.Authorization === "Bearer " + localStorage.getItem("accessToken")) {
    if (!refreshing) {
      const rotate = async () => {
        if (localStorage.getItem("id") !== config.sessionUser) throw new axios.CanceledError("Session changed.");
        if (localStorage.getItem("refreshToken") !== refreshToken) {
          if (localStorage.getItem("accessToken")) return;
          throw new axios.CanceledError("Session changed.");
        }
        const { data } = await axios.post(API_BASE_URL + "/api/token/refresh/", { refresh: refreshToken }, { timeout: 15000 });
        if (localStorage.getItem("refreshToken") !== refreshToken) throw new axios.CanceledError("Session changed.");
        localStorage.setItem("accessToken", data.access);
        localStorage.setItem("refreshToken", data.refresh);
        window.dispatchEvent(new Event("dam-session-change"));
      };
      refreshing = (globalThis.navigator?.locks?.request
        ? navigator.locks.request("dam-token-refresh", rotate) : rotate())
        .catch((refreshError) => {
          if (refreshError.response?.status === 401 && localStorage.getItem("refreshToken") === refreshToken) clearSession();
          throw refreshError;
        })
        .finally(() => { refreshing = null; });
    }
    await refreshing;
  }
  return api(config);
});

export async function downloadAsset(asset, filename) {
  const { data } = await api.get("/assets/" + asset.id + "/media-url/");
  const link = document.createElement("a");
  const url = new URL(data.url, API_BASE_URL + "/");
  url.searchParams.set("download", "1");
  link.href = url.href;
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
