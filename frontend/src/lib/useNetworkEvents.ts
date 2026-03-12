"use client";

import { useState, useCallback, useRef } from "react";
import type { AgentState } from "./useAgent";
import type { Channel } from "./api";

export interface NetworkEvent {
  id: string;
  timestamp: number;
  type: "discovery" | "channel_open" | "payment" | "channel_close" | "status";
  from: string;
  to?: string;
  message: string;
  meta?: string;
}

interface AgentSnapshot {
  channels: Channel[];
  peerCount: number;
}

/**
 * Tracks changes between polling cycles and generates synthetic events.
 * Works with any number of agents — no A/B bias.
 */
export function useNetworkEvents(agents: AgentState[], labelFn: (i: number) => string) {
  const [events, setEvents] = useState<NetworkEvent[]>([]);
  const prevSnapshots = useRef<Map<string, AgentSnapshot>>(new Map());

  const pushEvent = useCallback(
    (evt: Omit<NetworkEvent, "id" | "timestamp">) => {
      setEvents((prev) => {
        const next = [
          { ...evt, id: crypto.randomUUID(), timestamp: Date.now() },
          ...prev,
        ];
        return next.slice(0, 100);
      });
    },
    [],
  );

  const diffState = useCallback(() => {
    // Pre-build address → index map for O(1) lookups
    const addrToIdx = new Map<string, number>();
    agents.forEach((a, i) => {
      if (a.identity?.eth_address) addrToIdx.set(a.identity.eth_address, i);
    });

    const resolveLabel = (addr: string) => {
      const idx = addrToIdx.get(addr);
      return idx !== undefined ? labelFn(idx) : shortenTarget(addr);
    };

    agents.forEach((agent, i) => {
      if (!agent.online) return;
      const pid = agent.identity?.peer_id || `port-${i}`;
      const label = labelFn(i);
      const prev = prevSnapshots.current.get(pid) || { channels: [], peerCount: 0 };

      // New peers
      if (agent.peers.length > prev.peerCount) {
        const newCount = agent.peers.length - prev.peerCount;
        pushEvent({
          type: "discovery",
          from: label,
          message: `Discovered ${newCount} new peer${newCount > 1 ? "s" : ""} via mDNS`,
          meta: `Total: ${agent.peers.length}`,
        });
      }

      // Pre-build prev channel maps for O(1) lookups
      const prevIds = new Set(prev.channels.map((c) => c.channel_id));
      const prevChMap = new Map(prev.channels.map((c) => [c.channel_id, c]));

      // New channels
      for (const ch of agent.channels) {
        if (!prevIds.has(ch.channel_id)) {
          pushEvent({
            type: "channel_open",
            from: label,
            to: resolveLabel(ch.receiver),
            message: `Channel opened`,
            meta: `${ch.channel_id.slice(0, 12)}... deposit: ${ch.total_deposit}`,
          });
        }
      }

      // Payment changes (nonce increase) + state changes
      for (const ch of agent.channels) {
        const prevCh = prevChMap.get(ch.channel_id);
        if (!prevCh) continue;

        if (ch.nonce > prevCh.nonce) {
          const payments = ch.nonce - prevCh.nonce;
          pushEvent({
            type: "payment",
            from: label,
            to: resolveLabel(ch.receiver),
            message: `${payments} payment${payments > 1 ? "s" : ""} sent`,
            meta: `nonce: ${ch.nonce}, paid: ${ch.total_paid}`,
          });
        }

        if (prevCh.state !== ch.state) {
          pushEvent({
            type: ch.state === "CLOSING" || ch.state === "SETTLED" ? "channel_close" : "status",
            from: label,
            message: `Channel ${prevCh.state} → ${ch.state}`,
            meta: ch.channel_id.slice(0, 12) + "...",
          });
        }
      }

      prevSnapshots.current.set(pid, {
        channels: [...agent.channels],
        peerCount: agent.peers.length,
      });
    });
  }, [agents, labelFn, pushEvent]);

  return { events, diffState, pushEvent };
}

function shortenTarget(addr: string): string {
  if (addr.length > 12) return addr.slice(0, 6) + "..." + addr.slice(-4);
  return addr;
}
