"use client";

export default function NetworkIndicator({
  agentA,
  agentB,
  connected,
}: {
  agentA: boolean;
  agentB: boolean;
  connected: boolean;
}) {
  const onlineCount = (agentA ? 1 : 0) + (agentB ? 1 : 0);

  return (
    <div className="hidden sm:flex items-center gap-2.5 glass-card rounded-xl px-3.5 py-2">
      {/* Status indicator */}
      <span
        className={`w-2 h-2 rounded-full transition-colors duration-500 ${
          connected
            ? "bg-success animate-pulse-soft"
            : onlineCount > 0
              ? "bg-warning animate-pulse-soft"
              : "bg-text-muted/30"
        }`}
      />
      <span className="text-[11px] text-text-secondary font-medium">
        {connected ? "Connected" : onlineCount > 0 ? "Partial" : "Offline"}
      </span>
      <span className="text-[10px] font-mono text-text-muted/40">
        {onlineCount}/2
      </span>
    </div>
  );
}
