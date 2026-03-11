"use client";

import type { AgentState } from "@/lib/useAgent";
import { shortenId, shortenAddr, formatWei } from "@/lib/api";
import StatusBadge from "./StatusBadge";

const variants = {
  indigo: {
    dot: "bg-accent",
    label: "text-accent",
    ring: "group-hover:shadow-[0_0_24px_-8px_rgba(124,109,240,0.15)]",
    stat: "text-accent/80",
  },
  emerald: {
    dot: "bg-success",
    label: "text-success",
    ring: "group-hover:shadow-[0_0_24px_-8px_rgba(52,211,153,0.15)]",
    stat: "text-success/80",
  },
};

export default function AgentCard({
  agent,
  label,
  variant,
}: {
  agent: AgentState;
  label: string;
  variant: "indigo" | "emerald";
}) {
  const v = variants[variant];

  return (
    <div
      className={`group glass-card rounded-[var(--radius-card)] p-6 space-y-5 ${v.ring}`}
    >
      {/* Header row */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="relative">
            <span
              className={`block w-2.5 h-2.5 rounded-full transition-colors duration-500 ${
                agent.online ? v.dot : "bg-text-muted/30"
              }`}
            />
            {agent.online && (
              <span
                className={`absolute inset-0 w-2.5 h-2.5 rounded-full ${v.dot} animate-ping opacity-30`}
              />
            )}
          </div>
          <h2 className={`text-sm font-semibold tracking-wider uppercase ${v.label}`}>
            {label}
          </h2>
        </div>
        <StatusPill online={agent.online} />
      </div>

      {!agent.online ? (
        <div className="py-10 text-center">
          <div className="inline-flex items-center justify-center w-10 h-10 rounded-full bg-surface-overlay mb-3">
            <svg
              className="w-5 h-5 text-text-muted"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={1.5}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M5.636 5.636a9 9 0 1 0 12.728 0M12 3v9"
              />
            </svg>
          </div>
          <p className="text-text-muted text-sm">Node not running</p>
          <code className="text-text-muted/60 text-xs mt-1 block font-mono">
            uv run agentpay start
          </code>
        </div>
      ) : (
        <>
          {/* Identity */}
          {agent.identity && (
            <div className="space-y-3">
              <InfoRow
                label="Peer ID"
                value={shortenId(agent.identity.peer_id || "—", 8)}
                title={agent.identity.peer_id || undefined}
                mono
              />
              <InfoRow
                label="ETH Address"
                value={
                  agent.identity.eth_address
                    ? shortenAddr(agent.identity.eth_address)
                    : "—"
                }
                title={agent.identity.eth_address || undefined}
                mono
              />
              <InfoRow label="Connected" value={String(agent.connectedPeers)} />
            </div>
          )}

          {/* Balance stats */}
          {agent.balance && (
            <div className="pt-4 border-t border-border-subtle">
              <div className="grid grid-cols-3 gap-3">
                <StatCard
                  label="Deposited"
                  value={formatWei(agent.balance.total_deposited)}
                  accent={v.stat}
                />
                <StatCard
                  label="Paid"
                  value={formatWei(agent.balance.total_paid)}
                  accent={v.stat}
                />
                <StatCard
                  label="Remaining"
                  value={formatWei(agent.balance.total_remaining)}
                  accent={v.stat}
                />
              </div>
            </div>
          )}

          {/* Channels */}
          {agent.channels.length > 0 && (
            <div className="pt-4 border-t border-border-subtle space-y-2.5">
              <SectionLabel count={agent.channels.length}>Channels</SectionLabel>
              {agent.channels.map((ch) => (
                <div
                  key={ch.channel_id}
                  className="flex items-center justify-between gap-3 bg-surface-overlay/50 rounded-[var(--radius-badge)] px-3 py-2.5 transition-smooth hover:bg-surface-hover"
                >
                  <span className="font-mono text-xs text-text-secondary truncate min-w-0">
                    {shortenId(ch.channel_id, 6)}
                  </span>
                  <div className="flex items-center gap-2.5 shrink-0">
                    <span className="text-xs text-text-muted font-mono">
                      {formatWei(ch.total_paid)}
                    </span>
                    <StatusBadge state={ch.state} />
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Peers */}
          {agent.peers.length > 0 && (
            <div className="pt-4 border-t border-border-subtle space-y-2">
              <SectionLabel count={agent.peers.length}>Peers</SectionLabel>
              {agent.peers.map((p) => (
                <div key={p.peer_id} className="flex items-center gap-2.5 text-xs group/peer">
                  <span className="w-1.5 h-1.5 rounded-full bg-success/50 group-hover/peer:bg-success transition-colors" />
                  <span className="font-mono text-text-secondary truncate">
                    {shortenId(p.peer_id, 10)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

/* Sub-components */

function StatusPill({ online }: { online: boolean }) {
  return (
    <span
      className={`text-[10px] font-medium tracking-wide uppercase px-2.5 py-1 rounded-full transition-colors duration-500 ${
        online
          ? "bg-success-subtle text-success"
          : "bg-danger-subtle text-danger"
      }`}
    >
      {online ? "Online" : "Offline"}
    </span>
  );
}

function InfoRow({
  label,
  value,
  mono,
  title,
}: {
  label: string;
  value: string;
  mono?: boolean;
  title?: string;
}) {
  return (
    <div className="flex items-center justify-between gap-4 min-w-0">
      <span className="text-[10px] font-medium uppercase tracking-widest text-text-muted shrink-0">
        {label}
      </span>
      <span
        className={`text-[13px] truncate min-w-0 text-text-secondary ${
          mono ? "font-mono" : ""
        }`}
        title={title || value}
      >
        {value}
      </span>
    </div>
  );
}

function StatCard({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent: string;
}) {
  return (
    <div className="text-center bg-surface-overlay/30 rounded-[var(--radius-badge)] py-2.5 px-2">
      <p className="text-[10px] font-medium uppercase tracking-widest text-text-muted">
        {label}
      </p>
      <p className={`text-sm font-medium mt-1 ${accent}`}>{value}</p>
    </div>
  );
}

function SectionLabel({
  children,
  count,
}: {
  children: React.ReactNode;
  count: number;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] font-medium uppercase tracking-widest text-text-muted">
        {children}
      </span>
      <span className="text-[10px] font-mono text-text-muted/60 bg-surface-overlay rounded px-1.5 py-0.5">
        {count}
      </span>
    </div>
  );
}
