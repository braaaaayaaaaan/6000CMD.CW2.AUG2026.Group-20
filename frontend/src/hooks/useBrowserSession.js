"use client";

import { useEffect, useMemo, useSyncExternalStore } from "react";
import { restoreSession } from "@/utils/api";
import { getSessionSnapshot, getServerSnapshot, subscribeSession } from "@/utils/session";

export default function useBrowserSession() {
  const snapshot = useSyncExternalStore(subscribeSession, getSessionSnapshot, getServerSnapshot);
  useEffect(() => {
    void restoreSession();
    const refresh = () => { void restoreSession(true); };
    window.addEventListener("dam-auth-refresh", refresh);
    window.addEventListener("focus", refresh);
    return () => {
      window.removeEventListener("dam-auth-refresh", refresh);
      window.removeEventListener("focus", refresh);
    };
  }, []);
  return useMemo(() => snapshot === null
    ? { ready: false, authenticated: false, username: "", id: "", group: "" }
    : JSON.parse(snapshot), [snapshot]);
}
