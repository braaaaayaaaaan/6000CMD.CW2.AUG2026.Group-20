"use client";

import { useEffect, useState } from "react";
import { api, errorMessage } from "@/utils/api";
import useBrowserSession from "./useBrowserSession";

export default function useApiResource(path, { enabled = true, refreshKey = "" } = {}) {
  const session = useBrowserSession();
  const identity = session.id + ":" + session.group;
  const [revision, setRevision] = useState(0);
  const [result, setResult] = useState({ key: null, data: null, error: null, status: null });
  const key = enabled && session.authenticated && path ? JSON.stringify([path, identity, refreshKey, revision]) : null;

  useEffect(() => {
    if (!key) return;
    const controller = new AbortController();
    api.get(path, {
      signal: controller.signal,
    }).then(({ data }) => {
      if (!controller.signal.aborted) setResult({ key, path, identity, data, error: null, status: null });
    }).catch((error) => {
      if (!controller.signal.aborted) {
        setResult((previous) => ({
          key, path, identity,
          data: previous.path === path && previous.identity === identity ? previous.data : null,
          error: errorMessage(error),
          status: error.response?.status,
        }));
      }
    });
    return () => controller.abort();
  }, [path, identity, key]);

  function refresh() { setRevision((previous) => previous + 1); }
  function mutate(update) {
    setResult((previous) => ({
      ...previous, data: typeof update === "function" ? update(previous.data) : update,
    }));
  }
  const current = Boolean(key && result.key === key);
  const sameResource = Boolean(key && result.path === path && result.identity === identity);
  return {
    data: sameResource ? result.data : null,
    loading: Boolean(key && !current),
    error: current ? result.error : null,
    status: current ? result.status : null,
    refresh, mutate,
  };
}
