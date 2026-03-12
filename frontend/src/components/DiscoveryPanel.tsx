"use client";

import { useState, useEffect, useCallback } from "react";
import type { Api, DiscoveredAgent } from "@/lib/api";
import { shortenId, formatWei } from "@/lib/api";
import TrustBadge from "./TrustBadge";

interface DiscoveryPanelProps {
  api: Api;
  trustScores?: Record<string, number>;
}

export default function DiscoveryPanel({ api, trustScores = {} }: DiscoveryPanelProps) {
  const [agents, setAgents] = useState<DiscoveredAgent[]>([]);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const capability = filter.trim() || undefined;
      const res = await api.getDiscoveredAgents(capability);
      setAgents(res.agents);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, [api, filter]);

  useEffect(() => { refresh(); }, [refresh]);

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1.5">
        <input
          type="text"
          placeholder="Filter capability..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="flex-1 h-6 bg-surface-overlay border border-border rounded-md px-2 text-[10px] text-text-primary placeholder:text-text-muted focus-ring"
        />
        <button
          onClick={refresh}
          disabled={loading}
          className="h-6 px-2 text-[10px] bg-surface-overlay hover:bg-surface-hover border border-border rounded-md text-text-secondary disabled:opacity-40 transition-colors"
        >
          {loading ? "..." : "Refresh"}
        </button>
      </div>

      {agents.length === 0 ? (
        <p className="text-text-muted text-[10px] text-center py-3">No agents discovered</p>
      ) : (
        <div className="space-y-1.5">
          {agents.map((agent) => (
            <div key={agent.peer_id} className="bg-surface-overlay rounded-lg p-2 border border-border-subtle">
              <div className="flex items-center justify-between mb-0.5">
                <span className="text-[10px] font-mono text-text-secondary truncate">{shortenId(agent.peer_id)}</span>
                {trustScores[agent.peer_id] !== undefined && (
                  <TrustBadge score={trustScores[agent.peer_id]} />
                )}
              </div>
              <div className="text-[9px] text-text-muted font-mono truncate mb-1">{agent.eth_address}</div>
              {agent.capabilities.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {agent.capabilities.map((cap, i) => (
                    <span key={i} className="text-[9px] px-1.5 py-0.5 bg-accent/8 text-accent rounded-md border border-accent/15">
                      {cap.service_type} {formatWei(cap.price_per_call)}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
