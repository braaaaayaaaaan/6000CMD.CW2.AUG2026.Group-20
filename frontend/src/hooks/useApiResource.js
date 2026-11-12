"use client";

import { useEffect, useState } from "react";
import { api, errorMessage } from "@/utils/api";

export default function useApiResource(path, { enabled = true, accessToken = null, refreshKey = "" } = {}) {
  const [revision, setRevision] = useState(0);
  const [result, setResult] = useState({ key: null, data: null, error: null, status: null });
  const key = enabled && path ? JSON.stringify([path, accessToken, refreshKey, revision]) : null;

  useEffect(() => {
    if (!key) return;
    const controller = new AbortController();
    api.get(path, {
      signal: controller.signal,
      headers: accessToken ? { Authorization: "Bearer " + accessToken } : undefined,
    }).then(({ data }) => {
      if (!controller.signal.aborted) setResult({ key, path, accessToken, data, error: null, status: null });
    }).catch((error) => {
      if (!controller.signal.aborted) {
        setResult((previous) => ({
          key, path, accessToken,
          data: previous.path === path && previous.accessToken === accessToken ? previous.data : null,
          error: errorMessage(error),
          status: error.response?.status,
        }));
      }
    });
    return () => controller.abort();
  }, [path, accessToken, key]);

  function refresh() { setRevision((previous) => previous + 1); }
  function mutate(update) {
    setResult((previous) => ({
      ...previous, data: typeof update === "function" ? update(previous.data) : update,
    }));
  }
  const current = Boolean(key && result.key === key);
  const sameResource = Boolean(key && result.path === path && result.accessToken === accessToken);
  return {
    data: sameResource ? result.data : null,
    loading: Boolean(key && !current),
    error: current ? result.error : null,
    status: current ? result.status : null,
    refresh, mutate,
  };
}
