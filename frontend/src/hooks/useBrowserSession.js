"use client";

import { useMemo, useSyncExternalStore } from "react";

const eventName = "dam-session-change";
const emptySession = { accessToken: null, username: "", id: "", group: "" };
const getServerSnapshot = () => null;

function getSnapshot() {
  try {
    return JSON.stringify({
      accessToken: localStorage.getItem("accessToken"),
      username: localStorage.getItem("username") || "",
      id: localStorage.getItem("id") || "",
      group: localStorage.getItem("group") || "",
    });
  } catch {
    return JSON.stringify(emptySession);
  }
}

function subscribe(listener) {
  window.addEventListener("storage", listener);
  window.addEventListener(eventName, listener);
  return () => {
    window.removeEventListener("storage", listener);
    window.removeEventListener(eventName, listener);
  };
}

export function notifySessionChange() {
  window.dispatchEvent(new Event(eventName));
}

export default function useBrowserSession() {
  const snapshot = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  return useMemo(() => snapshot === null
    ? { ...emptySession, ready: false }
    : { ...JSON.parse(snapshot), ready: true }, [snapshot]);
}
