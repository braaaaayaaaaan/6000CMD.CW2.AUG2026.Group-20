"use client";

import { useEffect, useSyncExternalStore } from "react";
import { errorMessage, getAllPages } from "@/utils/api";
import useBrowserSession from "./useBrowserSession";

const initial = { tags: [], loading: true, error: null, revision: 0 };
let snapshot = initial;
let pending = null;
let controller = null;
let sessionId = null;
const listeners = new Set();
const getSnapshot = () => snapshot;
const getServerSnapshot = () => initial;

function publish(value) {
  snapshot = { ...snapshot, ...value };
  listeners.forEach((listener) => listener());
}

function loadTags(force = false) {
  if (pending && !force) return pending;
  if (!force && !snapshot.loading) return Promise.resolve();
  controller?.abort();
  const request = new AbortController();
  controller = request;
  publish({ loading: true, error: null });
  pending = getAllPages("/tags/?ordering=title", { signal: request.signal })
    .then((tags) => {
      if (!request.signal.aborted) {
        publish({ tags, loading: false, error: null, revision: snapshot.revision + 1 });
      }
    })
    .catch((error) => {
      if (!request.signal.aborted) publish({ loading: false, error: errorMessage(error, "Unable to load tags.") });
    })
    .finally(() => {
      if (controller === request) pending = null;
    });
  return pending;
}

function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export const refreshTags = () => loadTags(true);

export default function useTags() {
  const session = useBrowserSession();
  const value = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  useEffect(() => {
    if (!session.ready) return;
    if (session.id !== sessionId) {
      controller?.abort(); pending = null;
      sessionId = session.id;
      publish({ ...initial, revision: snapshot.revision + 1 });
    }
    if (session.accessToken) void loadTags();
  }, [session.ready, session.id, session.accessToken]);
  return { ...(session.id === sessionId ? value : initial), refresh: refreshTags };
}
