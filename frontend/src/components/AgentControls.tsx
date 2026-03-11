"use client";

import { useAgentManager, type ManagedAgent } from "@/lib/useAgentManager";
import { useAgent } from "@/lib/useAgent";

const AGENT_A_PORT = Number(process.env.NEXT_PUBLIC_AGENT_A_PORT || 8080);
const AGENT_B_PORT = Number(process.env.NEXT_PUBLIC_AGENT_B_PORT || 8081);

export default function AgentControls() {
  const { agents, loading, error, startAgent, stopAgent, startDefaultAgents } =
    useAgentManager();

  // Also check if agents are running externally (e.g. via dev.sh)
  const agentA = useAgent(AGENT_A_PORT);
  const agentB = useAgent(AGENT_B_PORT);

  const externallyRunning = (agentA.online || agentB.online) && agents.length === 0;
  const effectiveCount = externallyRunning
    ? (agentA.online ? 1 : 0) + (agentB.online ? 1 : 0)
    : agents.length;

  return (
    <div className="glass-card rounded-[var(--radius-card)] p-4 space-y-4">
      {/* Header + Add button */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-widest text-text-muted">
            Agent Processes
          </h3>
          <p className="text-[10px] text-text-muted mt-0.5">
            {effectiveCount} running{externallyRunning ? " (external)" : ""}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {!externallyRunning && agents.length === 0 && (
            <button
              onClick={startDefaultAgents}
              disabled={loading}
              className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-medium rounded-[var(--radius-button)] bg-success/10 text-success hover:bg-success/20 disabled:opacity-40 transition-colors"
            >
              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.347a1.125 1.125 0 0 1 0 1.972l-11.54 6.347a1.125 1.125 0 0 1-1.667-.986V5.653Z" />
              </svg>
              Boot All
            </button>
          )}
          <button
            onClick={() => startAgent()}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-medium rounded-[var(--radius-button)] bg-accent-subtle text-accent hover:bg-accent/20 disabled:opacity-40 transition-colors"
          >
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
            </svg>
            Add Node
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <p className="text-[11px] text-danger bg-danger-subtle rounded-[var(--radius-badge)] px-3 py-2 break-words">
          {error}
        </p>
      )}

      {/* Show externally running agents */}
      {externallyRunning && (
        <div className="space-y-2">
          {agentA.online && (
            <ExternalAgentRow label="Agent A" port={AGENT_A_PORT} peerId={agentA.identity?.peer_id} />
          )}
          {agentB.online && (
            <ExternalAgentRow label="Agent B" port={AGENT_B_PORT} peerId={agentB.identity?.peer_id} />
          )}
        </div>
      )}

      {/* Managed agent list */}
      {agents.length > 0 && (
        <div className="space-y-2">
          {agents.map((agent) => (
            <AgentRow
              key={agent.apiPort}
              agent={agent}
              onStop={() => stopAgent(agent.apiPort)}
              loading={loading}
            />
          ))}
        </div>
      )}

      {!externallyRunning && agents.length === 0 && !loading && (
        <div className="py-4 text-center">
          <p className="text-xs text-text-muted">
            No agents running. Click &quot;Boot All&quot; to start A + B, or &quot;Add Node&quot; for one.
          </p>
        </div>
      )}

      {loading && (
        <div className="flex items-center justify-center py-3 gap-2">
          <span className="w-3 h-3 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
          <span className="text-[11px] text-text-muted">Starting...</span>
        </div>
      )}
    </div>
  );
}

function ExternalAgentRow({
  label,
  port,
  peerId,
}: {
  label: string;
  port: number;
  peerId?: string | null;
}) {
  return (
    <div className="flex items-center justify-between gap-3 bg-surface-overlay/40 rounded-[var(--radius-badge)] px-3 py-2.5 transition-smooth hover:bg-surface-hover">
      <div className="flex items-center gap-3 min-w-0">
        <span className="w-2 h-2 rounded-full shrink-0 bg-success animate-pulse-soft" />
        <div className="min-w-0">
          <p className="text-xs font-medium text-text-secondary">{label}</p>
          <p className="text-[10px] font-mono text-text-muted truncate">
            API :{port} · External process
          </p>
        </div>
      </div>
      <span className="text-[9px] font-mono text-text-muted bg-surface-overlay px-1.5 py-0.5 rounded">
        external
      </span>
    </div>
  );
}

function AgentRow({
  agent,
  onStop,
  loading,
}: {
  agent: ManagedAgent;
  onStop: () => void;
  loading: boolean;
}) {
  const uptime = Math.floor((Date.now() - agent.startedAt) / 1000);
  const uptimeStr =
    uptime < 60
      ? `${uptime}s`
      : uptime < 3600
        ? `${Math.floor(uptime / 60)}m`
        : `${Math.floor(uptime / 3600)}h`;

  return (
    <div className="flex items-center justify-between gap-3 bg-surface-overlay/40 rounded-[var(--radius-badge)] px-3 py-2.5 transition-smooth hover:bg-surface-hover">
      <div className="flex items-center gap-3 min-w-0">
        <span
          className={`w-2 h-2 rounded-full shrink-0 ${
            agent.alive ? "bg-success animate-pulse-soft" : "bg-danger"
          }`}
        />
        <div className="min-w-0">
          <p className="text-xs font-medium text-text-secondary">
            {agent.label}
          </p>
          <p className="text-[10px] font-mono text-text-muted truncate">
            API :{agent.apiPort} &middot; P2P :{agent.port} &middot; WS :{agent.wsPort}
          </p>
        </div>
      </div>

      <div className="flex items-center gap-3 shrink-0">
        <span className="text-[10px] font-mono text-text-muted tabular-nums">
          {uptimeStr}
        </span>
        <span className="text-[10px] font-mono text-text-muted">
          pid:{agent.pid}
        </span>
        <button
          onClick={onStop}
          disabled={loading}
          className="text-danger/60 hover:text-danger hover:bg-danger-subtle p-1 rounded transition-colors disabled:opacity-30"
          title="Stop agent"
        >
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
    </div>
  );
}
