"use client";

import type { NetworkEvent } from "@/lib/useNetworkEvents";
import {
  Search,
  Zap,
  ArrowRightLeft,
  X,
  Info,
  Handshake,
  Fingerprint,
  HardDrive,
  ShieldCheck,
} from "lucide-react";
import type { ReactNode } from "react";

const typeConfig: Record<string, { color: string; icon: ReactNode; bg: string }> = {
  discovery: { color: "text-accent", icon: <Search size={11} />, bg: "bg-accent-subtle" },
  negotiate: { color: "text-accent", icon: <Handshake size={11} />, bg: "bg-accent-subtle" },
  channel_open: { color: "text-success", icon: <Zap size={11} />, bg: "bg-success-subtle" },
  payment: { color: "text-warning", icon: <ArrowRightLeft size={11} />, bg: "bg-warning-subtle" },
  channel_close: { color: "text-danger", icon: <X size={11} />, bg: "bg-danger-subtle" },
  erc8004: { color: "text-accent", icon: <Fingerprint size={11} />, bg: "bg-accent-subtle" },
  storage: { color: "text-accent", icon: <HardDrive size={11} />, bg: "bg-accent-subtle" },
  gateway: { color: "text-accent", icon: <ShieldCheck size={11} />, bg: "bg-accent-subtle" },
  status: { color: "text-text-secondary", icon: <Info size={11} />, bg: "bg-surface-overlay" },
};

export default function EventLog({ events }: { events: NetworkEvent[] }) {
  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border-subtle">
        <h3 className="text-[10px] font-medium uppercase tracking-widest text-text-muted">
          Event Log
        </h3>
        <span className="text-[10px] font-mono text-text-muted/60">
          {events.length} events
        </span>
      </div>

      {/* Events list */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {events.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <p className="text-xs text-text-muted/40">Waiting for events...</p>
          </div>
        ) : (
          <div className="divide-y divide-border-subtle">
            {events.map((evt) => (
              <EventRow key={evt.id} event={evt} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function EventRow({ event }: { event: NetworkEvent }) {
  const config = typeConfig[event.type] || typeConfig.status;
  const time = new Date(event.timestamp);
  const ts = `${time.getHours().toString().padStart(2, "0")}:${time.getMinutes().toString().padStart(2, "0")}:${time.getSeconds().toString().padStart(2, "0")}.${time.getMilliseconds().toString().padStart(3, "0").slice(0, 2)}`;

  return (
    <div className="flex items-start gap-3 px-4 py-2.5 hover:bg-surface-overlay/30 transition-colors">
      {/* Timestamp */}
      <span className="text-[10px] font-mono text-text-muted/50 shrink-0 pt-0.5 tabular-nums w-[60px]">
        {ts}
      </span>

      {/* Type badge — Lucide icon */}
      <span
        className={`shrink-0 w-5 h-5 rounded flex items-center justify-center ${config.bg} ${config.color}`}
      >
        {config.icon}
      </span>

      {/* Content */}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5 text-xs">
          <span className="font-medium text-text-secondary">{event.from}</span>
          {event.to && (
            <>
              <span className="text-text-muted/40">&rarr;</span>
              <span className="font-medium text-text-secondary">{event.to}</span>
            </>
          )}
        </div>
        <p className="text-[11px] text-text-muted mt-0.5">{event.message}</p>
        {event.meta && (
          <p className="text-[10px] font-mono text-text-muted/40 mt-0.5 truncate">
            {event.meta}
          </p>
        )}
      </div>
    </div>
  );
}
