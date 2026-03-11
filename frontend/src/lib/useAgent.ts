"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { createApi, Identity, Balance, Peer, Channel } from "./api";
import type { Api } from "./api";

export interface AgentState {
  online: boolean;
  identity: Identity | null;
  balance: Balance | null;
  peers: Peer[];
  channels: Channel[];
  connectedPeers: number;
  error: string | null;
  api: Api;
  refresh: () => void;
}

export function useAgent(port: number): AgentState {
  const [api] = useState(() => createApi(`http://127.0.0.1:${port}`));
  const [online, setOnline] = useState(false);
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [balance, setBalance] = useState<Balance | null>(null);
  const [peers, setPeers] = useState<Peer[]>([]);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [connectedPeers, setConnectedPeers] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const refresh = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      try {
        const [id, bal, p, ch] = await Promise.all([
          api.getIdentity(),
          api.getBalance(),
          api.getPeers(),
          api.getChannels(),
        ]);
        if (cancelled) return;
        setIdentity(id);
        setBalance(bal);
        setPeers(p.peers);
        setChannels(ch.channels);
        setConnectedPeers(p.connected ?? 0);
        setOnline(true);
        setError(null);
      } catch (err) {
        if (cancelled) return;
        setOnline(false);
        const message = err instanceof Error ? err.message : "Unknown error";
        setError(message.includes("fetch") || message.includes("Failed") ? "Node unreachable" : `API error: ${message}`);
      }
    };

    poll();
    const interval = setInterval(poll, 4000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [api, tick]);

  return useMemo(
    () => ({ online, identity, balance, peers, channels, connectedPeers, error, api, refresh }),
    [online, identity, balance, peers, channels, connectedPeers, error, api, refresh],
  );
}
