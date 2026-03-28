"use client";

import { useSyncExternalStore, useCallback, useRef, useEffect } from "react";

export type BackendStatus = "connecting" | "online" | "offline";

interface BackendState {
  status: BackendStatus;
  agentCount: number;
}

let globalState: BackendState = { status: "connecting", agentCount: 0 };
const listeners = new Set<() => void>();

function notify() {
  for (const l of listeners) l();
}

async function poll() {
  try {
    const res = await fetch("/api/agents");
    if (!res.ok) {
      globalState = { status: "offline", agentCount: 0 };
    } else {
      const data = await res.json();
      globalState = {
        status: data.backend === "online" ? "online" : "offline",
        agentCount: data.count ?? 0,
      };
    }
  } catch {
    globalState = { status: "offline", agentCount: 0 };
  }
  notify();
}

function subscribe(cb: () => void) {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

function getSnapshot() {
  return globalState;
}

function getServerSnapshot() {
  return { status: "connecting" as const, agentCount: 0 };
}

export function useBackendStatus(pollInterval = 8000) {
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    poll();
    const id = setInterval(poll, pollInterval);
    return () => clearInterval(id);
  }, [pollInterval]);

  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
