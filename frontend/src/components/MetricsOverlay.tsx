"use client";

import { useMemo } from "react";
import type { NetworkEvent } from "@/lib/useNetworkEvents";
import { formatWei } from "@/lib/api";

interface MetricsOverlayProps {
  events: NetworkEvent[];
  activeChannels: number;
  totalAgents: number;
}

export default function MetricsOverlay({
  events,
  activeChannels,
  totalAgents,
}: MetricsOverlayProps) {
  const metrics = useMemo(() => {
    const now = Date.now();
    const window = 15_000; // 15-second rolling window
    const recentPayments = events.filter(
      (e) => e.type === "payment" && now - e.timestamp < window
    );
    const tps = recentPayments.length / (window / 1000);

    // Parse throughput from meta strings (format: "nonce: X, paid: Y")
    let throughput = 0;
    for (const e of recentPayments) {
      if (e.meta) {
        const match = e.meta.match(/paid:\s*(\d+)/);
        if (match) throughput += parseInt(match[1], 10);
      }
    }

    return { tps, throughput, activeChannels, totalAgents };
  }, [events, activeChannels, totalAgents]);

  // Don't render if no meaningful data
  if (metrics.totalAgents === 0) return null;

  return (
    <div className="absolute bottom-14 left-3 z-10 flex items-center gap-2 px-3 py-1.5 rounded-lg bg-surface-primary/80 backdrop-blur-sm border border-border-subtle/30">
      <Metric label="TPS" value={metrics.tps.toFixed(1)} />
      <Sep />
      <Metric label="Throughput" value={formatWei(metrics.throughput)} />
      <Sep />
      <Metric label="Channels" value={String(metrics.activeChannels)} />
      <Sep />
      <Metric label="Agents" value={String(metrics.totalAgents)} />
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col items-center">
      <span className="text-[9px] text-text-muted/50 uppercase tracking-wider">{label}</span>
      <span className="text-[11px] font-mono text-text-primary font-medium">{value}</span>
    </div>
  );
}

function Sep() {
  return <span className="w-px h-5 bg-border-subtle/30" />;
}
