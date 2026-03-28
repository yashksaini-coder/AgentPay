"use client";

import { useState, useCallback, useEffect, useRef } from "react";

export interface ManagedAgent {
  apiPort: number;
  port: number;
  wsPort: number;
  pid: number;
  label: string;
  startedAt: number;
  alive: boolean;
  external?: boolean;
  // Discovery identity (populated in remote mode)
  peer_id?: string;
  eth_address?: string;
  capabilities?: { service_type: string; price_per_call: number; description: string; role?: string }[];
  addrs?: string[];
  /** true when this agent has a real running backend API */
  live?: boolean;
}

interface ManagerState {
  agents: ManagedAgent[];
  loading: boolean;
  error: string | null;
}

export function useAgentManager() {
  const [state, setState] = useState<ManagerState>({
    agents: [],
    loading: false,
    error: null,
  });
  const pollRef = useRef<ReturnType<typeof setInterval>>(undefined);

  const fetchAgents = useCallback(async () => {
    try {
      const res = await fetch("/api/agents");
      if (!res.ok) throw new Error("Failed to fetch agents");
      const data = await res.json();
      setState((prev) => ({ ...prev, agents: data.agents, error: null }));
    } catch {
      // API route not responding yet — agents may be empty
    }
  }, []);

  // Poll for agent list
  useEffect(() => {
    fetchAgents();
    pollRef.current = setInterval(fetchAgents, 10000);
    return () => clearInterval(pollRef.current);
  }, [fetchAgents]);

  const startAgent = useCallback(async (opts?: { apiPort?: number }) => {
    setState((prev) => ({ ...prev, loading: true, error: null }));
    try {
      const res = await fetch("/api/agents", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(opts ?? {}),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Failed to start agent");

      // Refresh list
      await fetchAgents();
      setState((prev) => ({ ...prev, loading: false }));
      return data.agent as ManagedAgent;
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed";
      setState((prev) => ({ ...prev, loading: false, error: msg }));
      return null;
    }
  }, [fetchAgents]);

  const stopAgent = useCallback(async (apiPort: number) => {
    setState((prev) => ({ ...prev, loading: true, error: null }));
    try {
      const res = await fetch("/api/agents", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ apiPort }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Failed to stop agent");

      await fetchAgents();
      setState((prev) => ({ ...prev, loading: false }));
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed";
      setState((prev) => ({ ...prev, loading: false, error: msg }));
    }
  }, [fetchAgents]);

  const startDefaultAgents = useCallback(async () => {
    setState((prev) => ({ ...prev, loading: true, error: null }));
    // Start 5 agents (A-E) on ports 8080-8084
    for (let i = 0; i < 5; i++) {
      await startAgent({ apiPort: 8080 + i });
    }
    setState((prev) => ({ ...prev, loading: false }));
  }, [startAgent]);

  return {
    ...state,
    startAgent,
    stopAgent,
    startDefaultAgents,
    refresh: fetchAgents,
  };
}
