"use client";

import { useEffect, useState, useCallback, useMemo, useRef } from "react";
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
  /** true when this agent has a live backend (vs. discovery-only) */
  live: boolean;
}

/** WebSocket state snapshot pushed by the backend /ws endpoint. */
interface WsSnapshot {
  type: "state";
  identity: Identity; // includes eip191_bound and verified_peers
  balance: Balance;
  peers: { peers: Peer[]; count: number; connected: number };
  channels: { channels: Channel[]; count: number };
}

/** Pre-populated identity from discovery (remote mode). */
export interface DiscoveryOverride {
  peer_id: string;
  eth_address: string;
  capabilities?: { service_type: string; price_per_call: number; description: string; role?: string }[];
  addrs?: string[];
  live: boolean;
}

function buildBaseUrl(port: number): string {
  const env = process.env.NEXT_PUBLIC_API_URL;
  // Remote deployment: use the env URL directly (single backend)
  if (env && !env.startsWith("/") && !env.includes("127.0.0.1") && !env.includes("localhost")) {
    return env;
  }
  return `http://127.0.0.1:${port}`;
}

function buildWsUrl(port: number): string {
  const env = process.env.NEXT_PUBLIC_API_URL;
  if (env && !env.startsWith("/") && !env.includes("127.0.0.1") && !env.includes("localhost")) {
    // Convert http(s) to ws(s)
    return env.replace(/^http/, "ws").replace(/\/$/, "") + "/ws";
  }
  return `ws://127.0.0.1:${port}/ws`;
}

export function useAgent(port: number, discovery?: DiscoveryOverride): AgentState {
  const isLive = discovery?.live ?? true;
  const discoveryIdentity: Identity | null = discovery && !discovery.live ? {
    peer_id: discovery.peer_id,
    eth_address: discovery.eth_address,
    addrs: discovery.addrs || [],
    eip191_bound: false,
    verified_peers: 0,
  } : null;

  const [api] = useState(() => createApi(buildBaseUrl(port)));
  const [online, setOnline] = useState(!isLive); // discovery-only agents are always "online"
  const [identity, setIdentity] = useState<Identity | null>(discoveryIdentity);
  const [balance, setBalance] = useState<Balance | null>(null);
  const [peers, setPeers] = useState<Peer[]>([]);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [connectedPeers, setConnectedPeers] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const refresh = useCallback(() => setTick((t) => t + 1), []);

  // Track whether WS is actively connected so we can skip HTTP polling
  const wsConnected = useRef(false);

  // ── WebSocket connection (only for live agents) ────────────
  useEffect(() => {
    if (!isLive) return; // Discovery-only agents don't need WS

    let cancelled = false;
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    function connect() {
      if (cancelled) return;
      ws = new WebSocket(buildWsUrl(port));

      ws.onopen = () => {
        console.log(`[WS:${port}] connected`);
        wsConnected.current = true;
      };

      ws.onmessage = (event) => {
        if (cancelled) return;
        try {
          const snap: WsSnapshot = JSON.parse(event.data);
          if (snap.type !== "state") return;
          setIdentity(snap.identity);
          setBalance(snap.balance);
          setPeers(snap.peers.peers);
          setChannels(snap.channels.channels);
          setConnectedPeers(snap.peers.connected ?? 0);
          setOnline(true);
          setError(null);
        } catch {
          // ignore malformed messages
        }
      };

      ws.onclose = (ev) => {
        console.log(`[WS:${port}] closed (code=${ev.code} reason=${ev.reason})`);
        wsConnected.current = false;
        if (!cancelled) {
          reconnectTimer = setTimeout(connect, 3000);
        }
      };

      ws.onerror = (ev) => {
        console.warn(`[WS:${port}] error`, ev);
        wsConnected.current = false;
        ws?.close();
      };
    }

    connect();

    return () => {
      cancelled = true;
      wsConnected.current = false;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, [port, isLive]);

  // ── HTTP polling fallback (only for live agents, only when WS is not connected) ───
  useEffect(() => {
    if (!isLive) return; // Discovery-only agents don't need polling

    let cancelled = false;

    const poll = async () => {
      // Skip if WebSocket is delivering data
      if (wsConnected.current) return;
      try {
        const [id, bal, p, ch] = await Promise.all([
          api.getIdentity(),
          api.getBalance(),
          api.getPeers(),
          api.getChannels(),
        ]);
        if (cancelled || wsConnected.current) return;
        setIdentity(id);
        setBalance(bal);
        setPeers(p.peers);
        setChannels(ch.channels);
        setConnectedPeers(p.connected ?? 0);
        setOnline(true);
        setError(null);
      } catch (err) {
        if (cancelled || wsConnected.current) return;
        setOnline(false);
        const message = err instanceof Error ? err.message : "Unknown error";
        setError(message.includes("fetch") || message.includes("Failed") ? "Node unreachable" : `API error: ${message}`);
      }
    };

    // Initial poll (WS may not be connected yet)
    poll();
    const interval = setInterval(poll, 8000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [api, tick, isLive]);

  return useMemo(
    () => ({ online, identity, balance, peers, channels, connectedPeers, error, api, refresh, live: isLive }),
    [online, identity, balance, peers, channels, connectedPeers, error, api, refresh, isLive],
  );
}
