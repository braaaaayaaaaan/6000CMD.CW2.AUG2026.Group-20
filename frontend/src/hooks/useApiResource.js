"use client";

import { useEffect, useRef, useState } from "react";
import { api, errorMessage } from "@/utils/api";
import useBrowserSession from "./useBrowserSession";

export default function useApiResource(path, {
  enabled = true, refreshKey = "",
  pollWhile = null, mergeData = null, onData = null, failureMessage = null,
} = {}) {
  const session = useBrowserSession();
  const identity = session.id + ":" + session.group;
  const [revision, setRevision] = useState(0);
  const [result, setResult] = useState({ key: null, data: null, error: null, status: null });
  const key = enabled && session.authenticated && path ? JSON.stringify([path, identity, refreshKey, revision]) : null;
  const callbacks = useRef({ mergeData, onData });
  useEffect(() => { callbacks.current = { mergeData, onData }; }, [mergeData, onData]);

  useEffect(() => {
    if (!key) return;
    const controller = new AbortController();
    let timer;
    let latest = null;
    async function load(initial = false) {
      if (controller.signal.aborted) return;
      if (!initial && document.hidden) {
        timer = setTimeout(() => load(), 2500);
        return;
      }
      let retry = true;
      try {
        const { data } = await api.get(path, {
          signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        latest = callbacks.current.mergeData ? callbacks.current.mergeData(latest, data) : data;
        callbacks.current.onData?.(latest);
        setResult({ key, path, identity, data: latest, error: null, status: null, pollError: null });
      } catch (error) {
        if (controller.signal.aborted) return;
        retry = ![401, 403, 404].includes(error.response?.status);
        setResult((previous) => ({
          key, path, identity,
          data: latest || (previous.path === path && previous.identity === identity ? previous.data : null),
          error: initial ? failureMessage || errorMessage(error) : null,
          status: error.response?.status,
          pollError: initial ? null : "Status updates are unavailable right now. Your file's last status is shown; you can refresh to check again.",
        }));
      }
      // Schedule only after completion, so requests never overlap. A transient
      // failure keeps the last backend state and retries without an error toast.
      if (retry && !controller.signal.aborted && pollWhile?.(latest))
        timer = setTimeout(() => load(), 2500);
    }
    load(true);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [path, identity, key, pollWhile, failureMessage]);

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
    pollError: current ? result.pollError : null,
    refresh, mutate,
  };
}
