"use client";

import type { NetworkEvent } from "@/lib/useNetworkEvents";

const typeConfig: Record<string, { color: string; icon: string; bg: string }> = {
  discovery: { color: "text-accent", icon: "D", bg: "bg-accent-subtle" },
  channel_open: { color: "text-success", icon: "C", bg: "bg-success-subtle" },
  payment: { color: "text-warning", icon: "$", bg: "bg-warning-subtle" },
  channel_close: { color: "text-danger", icon: "X", bg: "bg-danger-subtle" },
  status: { color: "text-text-secondary", icon: "i", bg: "bg-surface-overlay" },
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

      {/* Type badge */}
      <span
        className={`shrink-0 w-5 h-5 rounded flex items-center justify-center text-[10px] font-bold ${config.bg} ${config.color}`}
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
