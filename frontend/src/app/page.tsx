"use client";

import { useAgent } from "@/lib/useAgent";
import AgentCard from "@/components/AgentCard";
import ActionPanel from "@/components/ActionPanel";
import NetworkIndicator from "@/components/NetworkIndicator";
import AgentControls from "@/components/AgentControls";
import Nav from "@/components/Nav";

const AGENT_A_PORT = Number(process.env.NEXT_PUBLIC_AGENT_A_PORT || 8080);
const AGENT_B_PORT = Number(process.env.NEXT_PUBLIC_AGENT_B_PORT || 8081);

export default function Dashboard() {
  const agentA = useAgent(AGENT_A_PORT);
  const agentB = useAgent(AGENT_B_PORT);

  const bothOnline = agentA.online && agentB.online;

  return (
    <div className="max-w-[1200px] mx-auto px-5 sm:px-8 py-10 sm:py-16">
      {/* Header */}
      <header className="mb-14">
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-3.5">
              <h1 className="text-2xl sm:text-3xl font-semibold tracking-tight text-gradient">
                AgentPay
              </h1>
              <span className="text-[10px] font-mono text-text-muted bg-surface-overlay px-2 py-1 rounded-md border border-border">
                v0.1.0
              </span>
            </div>
            <p className="text-text-secondary text-sm mt-2 max-w-md leading-relaxed">
              Decentralized micropayment channels for autonomous AI agents over
              libp2p + Ethereum
            </p>
          </div>

          <div className="flex items-center gap-3">
            <Nav />
            <NetworkIndicator
              agentA={agentA.online}
              agentB={agentB.online}
              connected={bothOnline}
            />
          </div>
        </div>

        {/* Separator */}
        <div className="mt-8 h-px bg-gradient-to-r from-transparent via-border-focus to-transparent" />
      </header>

      {/* Agent process controls */}
      <div className="mb-8">
        <AgentControls />
      </div>

      {/* Main grid — agents flanking the action panel */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_340px_1fr] gap-5 items-start">
        <AgentCard agent={agentA} label="Agent A" variant="indigo" />

        <div className="w-full">
          <ActionPanel agentA={agentA} agentB={agentB} />
        </div>

        <AgentCard agent={agentB} label="Agent B" variant="emerald" />
      </div>

      {/* Separator */}
      <div className="mt-16 h-px bg-gradient-to-r from-transparent via-border-focus to-transparent" />
    </div>
  );
}
