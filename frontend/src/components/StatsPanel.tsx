"use client";

import type { AgentState } from "@/lib/useAgent";
import { formatWei, shortenAddr } from "@/lib/api";

export default function StatsPanel({
  agentA,
  agentB,
}: {
  agentA: AgentState;
  agentB: AgentState;
}) {
  const totalChannels = agentA.channels.length + agentB.channels.length;
  const activeChannels = agentA.channels.filter((c) => c.state === "ACTIVE").length;
  const totalDeposited = (agentA.balance?.total_deposited ?? 0) + (agentB.balance?.total_deposited ?? 0);
  const totalPaid = (agentA.balance?.total_paid ?? 0) + (agentB.balance?.total_paid ?? 0);
  const totalNonces = agentA.channels.reduce((s, c) => s + c.nonce, 0);

  return (
    <div className="flex flex-col h-full">
      {/* Network Nodes */}
      <Section title="Network Nodes">
        <StatRow label="Total Agents" value="2" />
        <StatRow
          label="Online"
          value={String((agentA.online ? 1 : 0) + (agentB.online ? 1 : 0))}
          color={(agentA.online && agentB.online) ? "text-success" : "text-warning"}
        />
        <StatRow label="Discovered Peers" value={String(agentA.peers.length)} />
        <StatRow label="Connected" value={String(agentA.connectedPeers)} />
      </Section>

      {/* Payment Channels */}
      <Section title="Payment Channels">
        <StatRow label="Total" value={String(totalChannels)} />
        <StatRow label="Active" value={String(activeChannels)} color={activeChannels > 0 ? "text-success" : undefined} />
        <StatRow label="Vouchers Sent" value={String(totalNonces)} />
      </Section>

      {/* Financial */}
      <Section title="Financial">
        <StatRow label="Deposited" value={formatWei(totalDeposited)} />
        <StatRow label="Transferred" value={formatWei(totalPaid)} color={totalPaid > 0 ? "text-warning" : undefined} />
      </Section>

      {/* Agent Details */}
      <Section title="Agent A" border={false}>
        <StatRow
          label="Status"
          value={agentA.online ? "Online" : "Offline"}
          color={agentA.online ? "text-success" : "text-danger"}
        />
        <StatRow
          label="ETH"
          value={agentA.identity?.eth_address ? shortenAddr(agentA.identity.eth_address) : "—"}
          mono
        />
        <StatRow label="Channels" value={String(agentA.channels.length)} />
      </Section>

      <Section title="Agent B" border={false}>
        <StatRow
          label="Status"
          value={agentB.online ? "Online" : "Offline"}
          color={agentB.online ? "text-success" : "text-danger"}
        />
        <StatRow
          label="ETH"
          value={agentB.identity?.eth_address ? shortenAddr(agentB.identity.eth_address) : "—"}
          mono
        />
        <StatRow label="Channels" value={String(agentB.channels.length)} />
      </Section>
    </div>
  );
}

function Section({
  title,
  children,
  border = true,
}: {
  title: string;
  children: React.ReactNode;
  border?: boolean;
}) {
  return (
    <div className={`px-4 py-3 ${border ? "border-b border-border-subtle" : ""}`}>
      <h3 className="text-[10px] font-semibold uppercase tracking-widest text-text-muted mb-2">
        {title}
      </h3>
      <div className="space-y-1.5">{children}</div>
    </div>
  );
}

function StatRow({
  label,
  value,
  color,
  mono,
}: {
  label: string;
  value: string;
  color?: string;
  mono?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-[11px] text-text-muted">{label}</span>
      <span
        className={`text-[11px] tabular-nums ${color ?? "text-text-secondary"} ${mono ? "font-mono" : "font-medium"}`}
      >
        {value}
      </span>
    </div>
  );
}
