"use client";

import { useEffect, useRef, useState, useMemo, useCallback } from "react";
import { useAgent, type AgentState } from "@/lib/useAgent";
import { useNetworkEvents, type NetworkEvent } from "@/lib/useNetworkEvents";
import { useAgentManager } from "@/lib/useAgentManager";
import { formatWei, type Channel } from "@/lib/api";
import Nav from "@/components/Nav";
import NetworkGraph, { type LoadingNode, type GraphInteraction, type AnimatingRoute } from "@/components/NetworkGraph";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import { Area, AreaChart, XAxis } from "recharts";

// Status colors for operations
const STATUS_EXECUTING = "#3b82f6";   // blue
const STATUS_COMPLETED = "#22c55e";   // green
const STATUS_FAILED = "#a855f7";      // purple
const NODE_NEUTRAL = "#8b8fa3";       // grey for dots

// ── AgentHook — render-less hook bridge ──
function AgentHook({ port, onState }: { port: number; onState: (port: number, state: AgentState) => void }) {
  const state = useAgent(port);
  const keyRef = useRef("");
  const key = `${state.online}|${state.identity?.peer_id}|${state.channels.length}|${state.peers.length}|${state.connectedPeers}`;
  useEffect(() => {
    if (key === keyRef.current) return;
    keyRef.current = key;
    onState(port, state);
  }, [key, port, state, onState]);
  return null;
}

// ── Main Page ──
export default function NetworkPage() {
  const manager = useAgentManager();
  const initRef = useRef(false);
  const [loadingNodes, setLoadingNodes] = useState<LoadingNode[]>([]);
  const [animatingRoute, setAnimatingRoute] = useState<AnimatingRoute | null>(null);

  // All agents tracked uniformly
  const [agentStates, setAgentStates] = useState<Map<number, AgentState>>(new Map());
  const agentPorts = useMemo(() => manager.agents.map((a) => a.apiPort), [manager.agents]);

  const handleAgentState = useCallback((port: number, state: AgentState) => {
    setAgentStates((prev) => {
      const next = new Map(prev);
      next.set(port, state);
      return next;
    });
  }, []);

  useEffect(() => {
    const portSet = new Set(agentPorts);
    setAgentStates((prev) => {
      const next = new Map(prev);
      let changed = false;
      for (const key of next.keys()) {
        if (!portSet.has(key)) { next.delete(key); changed = true; }
      }
      return changed ? next : prev;
    });
  }, [agentPorts]);

  const allAgents = useMemo(() => {
    const list: AgentState[] = [];
    for (const port of agentPorts) {
      const s = agentStates.get(port);
      if (s) list.push(s);
    }
    return list;
  }, [agentPorts, agentStates]);

  // Keep a ref to always-current agents for async simulation code
  const allAgentsRef = useRef(allAgents);
  allAgentsRef.current = allAgents;
  const getAgents = useCallback(() => allAgentsRef.current, []);

  const [agentNames, setAgentNames] = useState<Map<number, string>>(new Map());
  const agentLabel = useCallback((i: number) => {
    const port = manager.agents[i]?.apiPort ?? 8080 + i;
    return agentNames.get(port) || `Agent ${String.fromCharCode(65 + i)}`;
  }, [manager.agents, agentNames]);
  const { events, diffState, pushEvent } = useNetworkEvents(allAgents, agentLabel);

  const diffKey = allAgents.map((a) => `${a.online}|${a.channels.length}|${a.peers.length}`).join(",");
  useEffect(() => { diffState(); }, [diffState, diffKey]);

  useEffect(() => {
    if (initRef.current) return;
    initRef.current = true;
    pushEvent({ type: "status", from: "System", message: "Network monitor started" });
  }, [pushEvent]);

  // Metrics history
  const [paymentHistory, setPaymentHistory] = useState<{ t: string; amount: number }[]>([]);
  useEffect(() => {
    const paymentEvents = events.filter((e) => e.type === "payment");
    if (paymentEvents.length === 0) return;
    const latest = paymentEvents[0];
    const amountMatch = latest.message.match(/([\d,]+)/);
    if (amountMatch) {
      const ts = new Date(latest.timestamp).toLocaleTimeString("en-GB", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
      setPaymentHistory((prev) => {
        const next = [...prev, { t: ts, amount: parseInt(amountMatch[1].replace(/,/g, "")) }];
        return next.slice(-20);
      });
    }
  }, [events]);

  const onlineCount = allAgents.filter((a) => a.online).length;
  const totalChannels = allAgents.reduce((s, a) => s + a.channels.length, 0);
  const activeChannels = allAgents.reduce((s, a) => s + a.channels.filter((c) => c.state === "ACTIVE").length, 0);
  const hasAgents = agentPorts.length > 0;
  const onlineAgents = allAgents.filter((a) => a.online && a.identity?.peer_id);
  const lbl = (a: AgentState) => { const i = allAgents.indexOf(a); return i >= 0 ? agentLabel(i) : "Agent"; };
  const totalDeposited = allAgents.reduce((s, a) => s + (a.balance?.total_deposited ?? 0), 0);
  const totalPaid = allAgents.reduce((s, a) => s + (a.balance?.total_paid ?? 0), 0);
  const totalRemaining = allAgents.reduce((s, a) => s + (a.balance?.total_remaining ?? 0), 0);
  const totalPeers = allAgents.reduce((s, a) => s + a.peers.length, 0);

  // Collect all known channels from all agents for route-pay graph seeding
  const collectKnownChannels = useCallback(() => {
    const seen = new Set<string>();
    const channels: { channel_id: string; peer_a: string; peer_b: string; capacity: number }[] = [];
    for (const agent of allAgents) {
      const pid = agent.identity?.peer_id;
      if (!pid) continue;
      for (const ch of agent.channels) {
        if (seen.has(ch.channel_id)) continue;
        seen.add(ch.channel_id);
        // Find the other agent by eth_address to get peer_id
        const senderAgent = allAgents.find((a) => a.identity?.eth_address === ch.sender);
        const receiverAgent = allAgents.find((a) => a.identity?.eth_address === ch.receiver);
        const peerA = senderAgent?.identity?.peer_id;
        const peerB = receiverAgent?.identity?.peer_id;
        if (peerA && peerB && (ch.state === "ACTIVE" || ch.state === "OPEN")) {
          channels.push({ channel_id: ch.channel_id, peer_a: peerA, peer_b: peerB, capacity: ch.total_deposit });
        }
      }
    }
    return channels;
  }, [allAgents]);

  // ── Graph interaction: click-to-connect, pay, route-pay ──
  const [interaction, setInteraction] = useState<{
    mode: "channel" | "payment" | "route-pay";
    sourceAgent?: AgentState;
    targetAgent?: AgentState;
    channelId?: string;
  } | null>(null);
  const [interactionDeposit, setInteractionDeposit] = useState("1000000");
  const [interactionAmount, setInteractionAmount] = useState("100000");
  const [interactionLoading, setInteractionLoading] = useState(false);

  const handleGraphInteraction = useCallback((gi: GraphInteraction) => {
    if (gi.type === "node-pair") {
      const source = allAgents.find((a) => a.identity?.peer_id === gi.sourcePeerId);
      const target = allAgents.find((a) => a.identity?.peer_id === gi.targetPeerId);
      if (!source || !target) return;

      // Check if source (first-clicked node) has an outbound channel to target
      const chSourceToTarget = source.channels.find(
        (c) => c.state === "ACTIVE" && c.peer_id === gi.targetPeerId && c.sender === source.identity?.eth_address
      );

      if (chSourceToTarget) {
        // Source can pay target directly
        setInteraction({ mode: "payment", sourceAgent: source, targetAgent: target, channelId: chSourceToTarget.channel_id });
      } else {
        // No outbound channel from source → offer route-pay (HTLC) or open channel
        // Check if ANY channel exists between them (even reverse) to decide default mode
        const hasAnyChannel = source.channels.some(
          (c) => c.state === "ACTIVE" && c.peer_id === gi.targetPeerId
        ) || target.channels.some(
          (c) => c.state === "ACTIVE" && c.peer_id === gi.sourcePeerId
        );
        // If there's a reverse channel, suggest route-pay; otherwise open new channel
        setInteraction({
          mode: hasAnyChannel ? "route-pay" : "channel",
          sourceAgent: source,
          targetAgent: target,
        });
      }
    } else if (gi.type === "channel-click") {
      // Find the channel, then identify which agent is the sender (can pay)
      let senderAgent: typeof allAgents[0] | undefined;
      let ch: Channel | undefined;
      for (const a of allAgents) {
        const found = a.channels.find((c) => c.channel_id === gi.channelId);
        if (found && found.sender === a.identity?.eth_address) {
          senderAgent = a;
          ch = found;
          break;
        }
      }
      if (senderAgent && ch) {
        const receiverAgent = allAgents.find((a) => a.identity?.eth_address === ch!.receiver);
        setInteraction({ mode: "payment", sourceAgent: senderAgent, targetAgent: receiverAgent, channelId: ch.channel_id });
      }
    }
  }, [allAgents]);

  const handleOpenChannel = async () => {
    if (!interaction?.sourceAgent || !interaction.targetAgent) return;
    const sender = interaction.sourceAgent;
    const receiver = interaction.targetAgent;
    if (!receiver.identity?.peer_id || !receiver.identity?.eth_address) return;

    const sPid = sender.identity?.peer_id;
    const rPid = receiver.identity.peer_id;

    // Close popup, show connecting animation on both nodes
    setInteraction(null);
    const ln: LoadingNode[] = [];
    if (sPid) ln.push({ peerId: sPid, color: STATUS_EXECUTING });
    if (rPid) ln.push({ peerId: rPid, color: STATUS_EXECUTING });
    setLoadingNodes(ln);
    // Show animated route line between the two nodes during connection
    if (sPid && rPid) setAnimatingRoute({ hops: [sPid, rPid], color: STATUS_EXECUTING, type: "channel" });

    try {
      // Auto-connect peers before opening channel
      const addrs = receiver.identity?.addrs ?? [];
      const tcp = addrs.find((a) => a.includes("/tcp/") && !a.includes("/ws"));
      if (tcp) {
        const addr = tcp.replace("/ip4/0.0.0.0/", "/ip4/127.0.0.1/");
        const full = addr.includes("/p2p/") ? addr : `${addr}/p2p/${receiver.identity!.peer_id}`;
        try { await sender.api.connectPeer(full); } catch {}
      }
      const [res] = await Promise.all([
        sender.api.openChannel(receiver.identity.peer_id, receiver.identity.eth_address, parseInt(interactionDeposit)),
        new Promise((r) => setTimeout(r, 1800)),
      ]);
      setLoadingNodes([]); setAnimatingRoute(null);
      pushEvent({ type: "channel_open", from: lbl(sender), message: `Opened channel to ${lbl(receiver)}`, meta: `Deposit: ${parseInt(interactionDeposit).toLocaleString()} wei` });
      sender.refresh(); receiver.refresh();
    } catch (e: unknown) {
      setLoadingNodes([]); setAnimatingRoute(null);
      pushEvent({ type: "status", from: lbl(sender), message: `Channel open failed: ${e instanceof Error ? e.message : "unknown"}` });
    }
  };

  const handleRoutePayment = async () => {
    if (!interaction?.sourceAgent || !interaction.targetAgent) return;
    const sender = interaction.sourceAgent;
    const receiver = interaction.targetAgent;
    if (!receiver.identity?.peer_id) return;

    const amountVal = parseInt(interactionAmount);
    const sPid = sender.identity?.peer_id;
    const rPid = receiver.identity.peer_id;
    const knownChannels = collectKnownChannels();

    // Close dialog and show animation
    setInteraction(null);
    const ln: LoadingNode[] = [];
    if (sPid) ln.push({ peerId: sPid, color: STATUS_EXECUTING });
    if (rPid) ln.push({ peerId: rPid, color: STATUS_EXECUTING });
    setLoadingNodes(ln);

    try {
      // First find the route so we can animate it
      let routeHops: string[] = [];
      try {
        const routeRes = await sender.api.findRoute(rPid, amountVal, knownChannels);
        routeHops = [sPid!, ...routeRes.route.hops.map((h: { peer_id: string }) => h.peer_id)];
        setAnimatingRoute({ hops: routeHops, color: STATUS_EXECUTING, type: "payment" });
        const intermediateNodes: LoadingNode[] = routeHops.map((pid) => ({ peerId: pid, color: STATUS_EXECUTING }));
        setLoadingNodes(intermediateNodes);
      } catch {
        if (sPid && rPid) setAnimatingRoute({ hops: [sPid, rPid], color: STATUS_EXECUTING, type: "payment" });
      }

      const [res] = await Promise.all([
        sender.api.routePayment(rPid, amountVal, knownChannels),
        new Promise((r) => setTimeout(r, 2500)),
      ]);
      setLoadingNodes([]); setAnimatingRoute(null);
      const hops = res.payment.route.hop_count;
      pushEvent({
        type: "payment",
        from: lbl(sender),
        message: `Routed ${amountVal.toLocaleString()} wei to ${lbl(receiver)} (${hops} hop${hops > 1 ? "s" : ""})`,
        meta: `Hash: ${res.payment.payment_hash.slice(0, 12)}...`,
      });
      sender.refresh(); receiver.refresh();
    } catch (e: unknown) {
      setLoadingNodes([]); setAnimatingRoute(null);
      pushEvent({ type: "status", from: lbl(sender), message: `Route payment failed: ${e instanceof Error ? e.message : "unknown"}` });
    }
  };

  const handleSendPayment = async () => {
    if (!interaction?.sourceAgent || !interaction.channelId) return;
    const sender = interaction.sourceAgent;
    const channelId = interaction.channelId;
    const amountVal = parseInt(interactionAmount);
    const ch = sender.channels.find((c) => c.channel_id === channelId);
    const sPid = sender.identity?.peer_id;
    const rAgent = ch ? allAgents.find((a) => a.identity?.eth_address === ch.receiver) : null;
    const rPid = rAgent?.identity?.peer_id;

    // Close dialog immediately so user can see the transfer animation
    setInteraction(null);

    const ln: LoadingNode[] = [];
    if (sPid) ln.push({ peerId: sPid, color: STATUS_EXECUTING });
    if (rPid) ln.push({ peerId: rPid, color: STATUS_EXECUTING });
    setLoadingNodes(ln);
    if (sPid && rPid) setAnimatingRoute({ hops: [sPid, rPid], color: STATUS_EXECUTING, type: "payment" });

    try {
      const [res] = await Promise.all([
        sender.api.sendPayment(channelId, amountVal),
        new Promise((r) => setTimeout(r, 1800)),
      ]);
      setLoadingNodes([]); setAnimatingRoute(null);
      pushEvent({ type: "payment", from: lbl(sender), message: `Sent ${amountVal.toLocaleString()} wei`, meta: `Nonce: ${res.voucher.nonce}` });
      sender.refresh();
    } catch (e: unknown) {
      setLoadingNodes([]); setAnimatingRoute(null);
      pushEvent({ type: "status", from: lbl(sender), message: `Payment failed: ${e instanceof Error ? e.message : "unknown error"}` });
    }
  };

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      {agentPorts.map((port) => (
        <AgentHook key={port} port={port} onState={handleAgentState} />
      ))}

      {/* ── Top bar ── */}
      <header className="shrink-0 flex items-center justify-between px-4 py-2 border-b border-border-subtle z-10">
        <div className="flex items-center gap-3">
          <h1 className="text-xs font-semibold tracking-tight text-gradient">AgentPay</h1>
          <span className="w-px h-3 bg-border" />
          <Nav />
        </div>
        <div className="flex items-center gap-3">
          {manager.loading && <span className="w-2.5 h-2.5 border border-accent/30 border-t-accent rounded-full animate-spin" />}
        </div>
      </header>

      {/* ── Main: graph + sidebars ── */}
      <div className="flex-1 flex min-h-0">
        {/* ── Left: stats sidebar ── */}
        <aside className="w-[220px] shrink-0 border-r border-border-subtle overflow-y-auto p-3 space-y-4">
          <Section title="Network">
            <StatRow label="Nodes" value={`${onlineCount} / ${allAgents.length}`} />
            <StatRow label="Peers" value={String(totalPeers)} />
            <StatRow label="Channels" value={`${activeChannels} active / ${totalChannels}`} />
          </Section>

          <Section title="Financial">
            <StatRow label="Deposited" value={formatWei(totalDeposited)} accent />
            <StatRow label="Paid" value={formatWei(totalPaid)} />
            <StatRow label="Remaining" value={formatWei(totalRemaining)} />
          </Section>

          {paymentHistory.length > 1 && (
            <Section title="Payment Flow">
              <PaymentFlowChart data={paymentHistory} />
            </Section>
          )}
        </aside>

        {/* ── Center: graph ── */}
        <main className="flex-1 relative min-h-0">
          <NetworkGraph agents={allAgents} loadingNodes={loadingNodes} animatingRoute={animatingRoute} onInteraction={handleGraphInteraction} agentLabels={agentLabel} />

          {/* Interaction popup overlay */}
          {interaction && (
            <div className="absolute inset-0 flex items-center justify-center z-20 pointer-events-none">
              <div className="pointer-events-auto glass-card rounded-xl p-4 w-[300px] shadow-2xl border border-border-focus">
                <InteractionPopup
                  interaction={interaction}
                  interactionDeposit={interactionDeposit}
                  setInteractionDeposit={setInteractionDeposit}
                  interactionAmount={interactionAmount}
                  setInteractionAmount={setInteractionAmount}
                  interactionLoading={interactionLoading}
                  onClose={() => setInteraction(null)}
                  onOpenChannel={handleOpenChannel}
                  onSendPayment={handleSendPayment}
                  onRoutePayment={handleRoutePayment}
                  onSwitchToRoutePay={() => setInteraction((prev) => prev ? { ...prev, mode: "route-pay" } : null)}
                  onSwitchToChannel={() => setInteraction((prev) => prev ? { ...prev, mode: "channel" } : null)}
                  lbl={lbl}
                  allAgents={allAgents}
                />
              </div>
            </div>
          )}

          {/* Hint bar */}
          <div className="absolute bottom-3 left-1/2 -translate-x-1/2 z-10">
            <div className="glass-card rounded-lg px-3 py-1.5 text-[10px] text-text-secondary">
              Click two nodes to connect or pay · Click a channel line to send direct payment · Multi-hop routes auto-discovered
            </div>
          </div>

          {!hasAgents && (
            <div className="absolute inset-0 flex items-center justify-center bg-surface/60 backdrop-blur-sm z-10">
              <div className="text-center">
                <p className="text-sm text-text-secondary mb-3">No agents running</p>
                <Button onClick={manager.startDefaultAgents} disabled={manager.loading} size="sm">
                  {manager.loading ? "Starting..." : "Start Agents"}
                </Button>
              </div>
            </div>
          )}
        </main>

        {/* ── Right: actions + events ── */}
        <aside className="w-[280px] shrink-0 border-l border-border-subtle flex flex-col">
          <Tabs defaultValue="events" className="flex flex-col flex-1 min-h-0">
            <TabsList className="w-full justify-start rounded-none border-b border-border-subtle bg-transparent px-2 h-9">
              <TabsTrigger value="events" className="text-[11px] data-[state=active]:text-text-primary data-[state=active]:shadow-none rounded-md px-2.5 py-1">
                Events{events.length > 0 ? ` (${events.length})` : ""}
              </TabsTrigger>
              <TabsTrigger value="actions" className="text-[11px] data-[state=active]:text-text-primary data-[state=active]:shadow-none rounded-md px-2.5 py-1">Actions</TabsTrigger>
            </TabsList>

            <TabsContent value="events" className="flex-1 overflow-y-auto mt-0">
              <EventsList events={events} />
            </TabsContent>

            <TabsContent value="actions" className="flex-1 overflow-y-auto p-3 space-y-3 mt-0">
              <div className="flex gap-1.5">
                {!hasAgents && (
                  <Button onClick={manager.startDefaultAgents} disabled={manager.loading} size="sm" className="flex-1 text-[10px] h-7">
                    Boot Agents
                  </Button>
                )}
                <Button onClick={() => manager.startAgent()} disabled={manager.loading} variant="outline" size="sm" className="flex-1 text-[10px] h-7">
                  + Add Node
                </Button>
              </div>

              <div className="rounded-lg border border-border-subtle p-3 space-y-2">
                <h4 className="text-[10px] font-semibold uppercase tracking-widest text-text-muted">Quick Connect</h4>
                <p className="text-[10px] text-text-secondary leading-relaxed">
                  Click two agent nodes to open a channel or send payment. Click a channel line for direct payment. Nodes without a direct channel can use multi-hop routing.
                </p>
              </div>

              <SimulationPanel
                manager={manager} allAgents={allAgents} onlineAgents={onlineAgents} lbl={lbl} agentLabel={agentLabel}
                setLoadingNodes={setLoadingNodes} setAnimatingRoute={setAnimatingRoute}
                collectKnownChannels={collectKnownChannels} pushEvent={pushEvent}
                agentNames={agentNames} setAgentNames={setAgentNames}
                getAgents={getAgents}
              />
              <RoutePaymentForm agents={allAgents} onlineAgents={onlineAgents} lbl={lbl} setLoadingNodes={setLoadingNodes} setAnimatingRoute={setAnimatingRoute} collectKnownChannels={collectKnownChannels} pushEvent={pushEvent} />
              <FallbackOpenChannelForm agents={allAgents} onlineAgents={onlineAgents} lbl={lbl} pushEvent={pushEvent} />
              <FallbackSendPaymentForm agents={allAgents} onlineAgents={onlineAgents} lbl={lbl} setLoadingNodes={setLoadingNodes} pushEvent={pushEvent} />
            </TabsContent>
          </Tabs>
        </aside>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════
// Left sidebar components
// ═══════════════════════════════════════════════════════════

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="text-[10px] font-bold uppercase tracking-widest text-text-muted mb-2">{title}</h3>
      <div className="space-y-1">{children}</div>
    </div>
  );
}

function StatRow({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="flex items-center justify-between text-[11px]">
      <span className="text-text-muted">{label}</span>
      <span className={`font-mono tabular-nums ${accent ? "text-accent" : "text-text-primary"}`}>{value}</span>
    </div>
  );
}


// ═══════════════════════════════════════════════════════════
// Charts
// ═══════════════════════════════════════════════════════════

const flowChartConfig: ChartConfig = {
  amount: { label: "Amount", color: "#fbbf24" },
};

function PaymentFlowChart({ data }: { data: { t: string; amount: number }[] }) {
  return (
    <ChartContainer config={flowChartConfig} className="h-[80px] w-full">
      <AreaChart data={data}>
        <XAxis dataKey="t" tickLine={false} axisLine={false} tick={{ fontSize: 8, fill: "#7a7a94" }} interval="preserveStartEnd" />
        <ChartTooltip content={<ChartTooltipContent />} />
        <defs>
          <linearGradient id="fillAmount" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#fbbf24" stopOpacity={0.3} />
            <stop offset="100%" stopColor="#fbbf24" stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <Area type="monotone" dataKey="amount" stroke="#fbbf24" strokeWidth={1.5} fill="url(#fillAmount)" />
      </AreaChart>
    </ChartContainer>
  );
}

// ═══════════════════════════════════════════════════════════
// Events list
// ═══════════════════════════════════════════════════════════

const TYPE_BADGE: Record<string, { bg: string; text: string; letter: string }> = {
  discovery: { bg: "bg-accent/10", text: "text-accent", letter: "D" },
  channel_open: { bg: "bg-success/10", text: "text-success", letter: "C" },
  payment: { bg: "bg-warning/10", text: "text-warning", letter: "$" },
  channel_close: { bg: "bg-danger/10", text: "text-danger", letter: "X" },
  status: { bg: "bg-surface-overlay", text: "text-text-muted", letter: "i" },
};

function EventsList({ events }: { events: NetworkEvent[] }) {
  if (events.length === 0) return <p className="text-[11px] text-text-muted text-center py-8">No events yet</p>;
  return (
    <div className="divide-y divide-border-subtle">
      {events.slice(0, 50).map((evt) => {
        const badge = TYPE_BADGE[evt.type] || TYPE_BADGE.status;
        return (
          <div key={evt.id} className="flex items-start gap-2 px-3 py-2 hover:bg-surface-overlay/30">
            <span className={`shrink-0 w-4 h-4 rounded text-[8px] font-bold flex items-center justify-center mt-0.5 ${badge.bg} ${badge.text}`}>
              {badge.letter}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline gap-1.5">
                <span className="text-[11px] font-medium text-text-primary">{evt.from}</span>
                <span className="text-[9px] font-mono text-text-muted tabular-nums">
                  {new Date(evt.timestamp).toLocaleTimeString("en-GB", { hour12: false })}
                </span>
              </div>
              <p className="text-[10px] text-text-secondary leading-tight">{evt.message}</p>
              {evt.meta && <p className="text-[9px] font-mono text-text-muted mt-0.5">{evt.meta}</p>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════
// Fallback sidebar forms (kept as backup)
// ═══════════════════════════════════════════════════════════

function RoutePaymentForm({ agents, onlineAgents, lbl, setLoadingNodes, setAnimatingRoute, collectKnownChannels, pushEvent }: {
  agents: AgentState[];
  onlineAgents: AgentState[];
  lbl: (a: AgentState) => string;
  setLoadingNodes: React.Dispatch<React.SetStateAction<LoadingNode[]>>;
  setAnimatingRoute: React.Dispatch<React.SetStateAction<AnimatingRoute | null>>;
  collectKnownChannels: () => { channel_id: string; peer_a: string; peer_b: string; capacity: number }[];
  pushEvent: (e: Omit<NetworkEvent, "id" | "timestamp">) => void;
}) {
  const [senderIdx, setSenderIdx] = useState("0");
  const [receiverIdx, setReceiverIdx] = useState("");
  const [amount, setAmount] = useState("100000");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; msg: string } | null>(null);

  if (onlineAgents.length < 2) return null;

  const sender = onlineAgents[parseInt(senderIdx)];

  // Filter receivers to those the sender does NOT have a direct active channel to
  const potentialReceivers = onlineAgents.filter((a, i) => {
    if (String(i) === senderIdx) return false;
    if (!a.identity?.peer_id) return false;
    // Include all other agents — route-pay works whether there's a direct channel or not
    return true;
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!sender || !receiverIdx) return;
    const receiver = onlineAgents[parseInt(receiverIdx)];
    if (!receiver?.identity?.peer_id) { setResult({ ok: false, msg: "Select a destination" }); return; }

    const sPid = sender.identity?.peer_id;
    const rPid = receiver.identity.peer_id;
    const amountVal = parseInt(amount);
    const knownChannels = collectKnownChannels();

    setLoading(true); setResult(null);
    const ln: LoadingNode[] = [];
    if (sPid) ln.push({ peerId: sPid, color: STATUS_EXECUTING });
    if (rPid) ln.push({ peerId: rPid, color: STATUS_EXECUTING });
    setLoadingNodes(ln);

    try {
      // Find route first for animation
      try {
        const routeRes = await sender.api.findRoute(rPid, amountVal, knownChannels);
        const routeHops = [sPid!, ...routeRes.route.hops.map((h: { peer_id: string }) => h.peer_id)];
        setAnimatingRoute({ hops: routeHops, color: STATUS_EXECUTING, type: "payment" });
        setLoadingNodes(routeHops.map((pid) => ({ peerId: pid, color: STATUS_EXECUTING })));
      } catch {
        if (sPid && rPid) setAnimatingRoute({ hops: [sPid, rPid], color: STATUS_EXECUTING, type: "payment" });
      }

      const [res] = await Promise.all([
        sender.api.routePayment(rPid, amountVal, knownChannels),
        new Promise((r) => setTimeout(r, 2500)),
      ]);
      setLoadingNodes([]); setAnimatingRoute(null);
      const hops = res.payment.route.hop_count;
      setResult({ ok: true, msg: `Routed via ${hops} hop${hops > 1 ? "s" : ""}` });
      setAmount("");
      pushEvent({
        type: "payment",
        from: lbl(sender),
        message: `Routed ${amountVal.toLocaleString()} wei to ${lbl(receiver)} (${hops} hop${hops > 1 ? "s" : ""})`,
        meta: `Hash: ${res.payment.payment_hash.slice(0, 16)}...`,
      });
      sender.refresh(); receiver.refresh();
    } catch (err: unknown) {
      setLoadingNodes([]); setAnimatingRoute(null);
      setResult({ ok: false, msg: err instanceof Error ? err.message : "Failed" });
    } finally { setLoading(false); }
  };

  return (
    <div className="rounded-lg border border-warning/20 bg-warning/[0.03] p-3 space-y-2">
      <div className="flex items-center gap-1.5">
        <h4 className="text-[10px] font-semibold uppercase tracking-widest text-warning">Route Payment</h4>
        <span className="text-[8px] font-bold uppercase px-1 py-0.5 rounded bg-warning/15 text-warning">HTLC</span>
      </div>
      <p className="text-[9px] text-text-muted leading-relaxed">
        Send payment via multi-hop routing through intermediate nodes. No direct channel needed.
      </p>
      <form onSubmit={handleSubmit} className="space-y-2">
        <div className="flex gap-2 items-end">
          <div className="flex-1">
            <label className="text-[9px] font-medium text-text-muted block mb-1">From</label>
            <Select value={senderIdx} onValueChange={(v) => { setSenderIdx(v); setReceiverIdx(""); }}>
              <SelectTrigger className="h-7 text-[10px] bg-surface-overlay border-border">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {onlineAgents.map((a, i) => <SelectItem key={i} value={String(i)} className="text-[10px]">{lbl(a)}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <span className="text-warning pb-1 text-xs">→···→</span>
          <div className="flex-1">
            <label className="text-[9px] font-medium text-text-muted block mb-1">To</label>
            <Select value={receiverIdx} onValueChange={setReceiverIdx}>
              <SelectTrigger className="h-7 text-[10px] bg-surface-overlay border-border">
                <SelectValue placeholder="Select..." />
              </SelectTrigger>
              <SelectContent>
                {potentialReceivers.map((a) => {
                  const idx = onlineAgents.indexOf(a);
                  return <SelectItem key={idx} value={String(idx)} className="text-[10px]">{lbl(a)}</SelectItem>;
                })}
              </SelectContent>
            </Select>
          </div>
        </div>
        <div>
          <label className="text-[9px] font-medium text-text-muted block mb-1">Amount (wei)</label>
          <input value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="100000" required min="1" type="number" disabled={loading}
            className="w-full h-7 bg-surface-overlay border border-border rounded-md px-2 text-[10px] font-mono text-text-primary placeholder:text-text-muted focus-ring disabled:opacity-50" />
        </div>

        <Button type="submit" disabled={loading || !receiverIdx || senderIdx === receiverIdx} variant="secondary" size="sm" className="w-full h-7 text-[10px] bg-warning/80 hover:bg-warning text-black font-semibold">
          {loading ? "Routing..." : "Route Payment (HTLC)"}
        </Button>
      </form>
    </div>
  );
}

function FallbackOpenChannelForm({ agents, onlineAgents, lbl, pushEvent }: {
  agents: AgentState[];
  onlineAgents: AgentState[];
  lbl: (a: AgentState) => string;
  pushEvent: (e: Omit<NetworkEvent, "id" | "timestamp">) => void;
}) {
  const [senderIdx, setSenderIdx] = useState("0");
  const [receiverIdx, setReceiverIdx] = useState("1");
  const [deposit, setDeposit] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; msg: string } | null>(null);

  if (onlineAgents.length < 2) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const si = parseInt(senderIdx);
    const ri = parseInt(receiverIdx);
    const sender = onlineAgents[si];
    const receiver = onlineAgents[ri];
    if (!sender || !receiver || si === ri || !receiver.identity?.peer_id || !receiver.identity?.eth_address) {
      setResult({ ok: false, msg: "Select two different agents" }); return;
    }
    setLoading(true); setResult(null);
    try {
      const addrs = receiver.identity?.addrs ?? [];
      const tcp = addrs.find((a) => a.includes("/tcp/") && !a.includes("/ws"));
      if (tcp) {
        const addr = tcp.replace("/ip4/0.0.0.0/", "/ip4/127.0.0.1/");
        const full = addr.includes("/p2p/") ? addr : `${addr}/p2p/${receiver.identity!.peer_id}`;
        try { await sender.api.connectPeer(full); } catch {}
      }
      const res = await sender.api.openChannel(receiver.identity.peer_id, receiver.identity.eth_address, parseInt(deposit));
      setResult({ ok: true, msg: `${res.channel.channel_id.slice(0, 12)}...` });
      setDeposit("");
      pushEvent({ type: "channel_open", from: lbl(sender), message: `Opened channel to ${lbl(receiver)}`, meta: `Deposit: ${parseInt(deposit).toLocaleString()} wei` });
      sender.refresh(); receiver.refresh();
    } catch (e: unknown) { setResult({ ok: false, msg: e instanceof Error ? e.message : "Failed" }); }
    finally { setLoading(false); }
  };

  return (
    <details className="group">
      <summary className="text-[10px] font-semibold uppercase tracking-widest text-text-muted cursor-pointer hover:text-text-secondary transition-colors">
        Open Channel (form)
      </summary>
      <form onSubmit={handleSubmit} className="space-y-2 mt-2">
        <div className="flex gap-2 items-end">
          <div className="flex-1">
            <label className="text-[9px] font-medium text-text-muted block mb-1">From</label>
            <Select value={senderIdx} onValueChange={setSenderIdx}>
              <SelectTrigger className="h-7 text-[10px] bg-surface-overlay border-border">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {onlineAgents.map((a, i) => <SelectItem key={i} value={String(i)} className="text-[10px]">{lbl(a)}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <span className="text-text-muted pb-1 text-xs">&rarr;</span>
          <div className="flex-1">
            <label className="text-[9px] font-medium text-text-muted block mb-1">To</label>
            <Select value={receiverIdx} onValueChange={setReceiverIdx}>
              <SelectTrigger className="h-7 text-[10px] bg-surface-overlay border-border">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {onlineAgents.map((a, i) => <SelectItem key={i} value={String(i)} className="text-[10px]">{lbl(a)}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
        </div>
        <div>
          <label className="text-[9px] font-medium text-text-muted block mb-1">Deposit (wei)</label>
          <input value={deposit} onChange={(e) => setDeposit(e.target.value)} placeholder="1000000" required min="1" type="number"
            className="w-full h-7 bg-surface-overlay border border-border rounded-md px-2 text-[10px] font-mono text-text-primary placeholder:text-text-muted focus-ring" />
        </div>

        <Button type="submit" disabled={loading || senderIdx === receiverIdx} size="sm" className="w-full h-7 text-[10px]">
          {loading ? "Opening..." : "Open Channel"}
        </Button>
      </form>
    </details>
  );
}

function FallbackSendPaymentForm({ agents, onlineAgents, lbl, setLoadingNodes, pushEvent }: {
  agents: AgentState[];
  onlineAgents: AgentState[];
  lbl: (a: AgentState) => string;
  setLoadingNodes: React.Dispatch<React.SetStateAction<LoadingNode[]>>;
  pushEvent: (e: Omit<NetworkEvent, "id" | "timestamp">) => void;
}) {
  const [senderIdx, setSenderIdx] = useState("0");
  const [channelId, setChannelId] = useState("");
  const [amount, setAmount] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; msg: string } | null>(null);

  const sender = onlineAgents[parseInt(senderIdx)];
  const activeChannels = sender?.channels.filter((c) => c.state === "ACTIVE") ?? [];

  if (onlineAgents.length === 0) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!sender) return;
    const ch = sender.channels.find((c) => c.channel_id === channelId);
    const sPid = sender.identity?.peer_id;
    const rAgent = ch ? agents.find((a) => a.identity?.eth_address === ch.receiver) : null;
    const rPid = rAgent?.identity?.peer_id;

    setLoading(true); setResult(null);
    const ln: LoadingNode[] = [];
    if (sPid) ln.push({ peerId: sPid, color: STATUS_EXECUTING });
    if (rPid) ln.push({ peerId: rPid, color: STATUS_EXECUTING });
    setLoadingNodes(ln);

    try {
      const [res] = await Promise.all([
        sender.api.sendPayment(channelId, parseInt(amount)),
        new Promise((r) => setTimeout(r, 1800)),
      ]);
      setLoadingNodes([]);
      setResult({ ok: true, msg: `Nonce ${res.voucher.nonce} — ${res.voucher.amount.toLocaleString()} wei` });
      setAmount("");
      pushEvent({ type: "payment", from: lbl(sender), message: `Sent ${parseInt(amount).toLocaleString()} wei`, meta: `Nonce: ${res.voucher.nonce}` });
      sender.refresh();
    } catch (e: unknown) {
      setLoadingNodes([]);
      setResult({ ok: false, msg: e instanceof Error ? e.message : "Failed" });
    } finally { setLoading(false); }
  };

  return (
    <details className="group">
      <summary className="text-[10px] font-semibold uppercase tracking-widest text-text-muted cursor-pointer hover:text-text-secondary transition-colors">
        Send Payment (form)
      </summary>
      <form onSubmit={handleSubmit} className="space-y-2 mt-2">
        <div>
          <label className="text-[9px] font-medium text-text-muted block mb-1">Sender</label>
          <Select value={senderIdx} onValueChange={(v) => { setSenderIdx(v); setChannelId(""); }}>
            <SelectTrigger className="h-7 text-[10px] bg-surface-overlay border-border">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {onlineAgents.map((a, i) => <SelectItem key={i} value={String(i)} className="text-[10px]">{lbl(a)}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div>
          <label className="text-[9px] font-medium text-text-muted block mb-1">Channel</label>
          {activeChannels.length > 0 ? (
            <Select value={channelId} onValueChange={setChannelId}>
              <SelectTrigger className="h-7 text-[10px] bg-surface-overlay border-border font-mono">
                <SelectValue placeholder="Select channel..." />
              </SelectTrigger>
              <SelectContent>
                {activeChannels.map((ch) => (
                  <SelectItem key={ch.channel_id} value={ch.channel_id} className="text-[10px] font-mono">
                    {ch.channel_id.slice(0, 10)}... ({ch.remaining_balance.toLocaleString()} left)
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : <p className="text-[10px] text-text-muted text-center py-1.5 border border-dashed border-border-subtle rounded-md">No active channels</p>}
        </div>
        <div>
          <label className="text-[9px] font-medium text-text-muted block mb-1">Amount (wei)</label>
          <input value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="100000" required min="1" type="number" disabled={loading}
            className="w-full h-7 bg-surface-overlay border border-border rounded-md px-2 text-[10px] font-mono text-text-primary placeholder:text-text-muted focus-ring disabled:opacity-50" />
        </div>

        <Button type="submit" disabled={loading || !channelId} variant="secondary" size="sm" className="w-full h-7 text-[10px] bg-success/80 hover:bg-success text-white">
          {loading ? "Transferring..." : "Send Payment"}
        </Button>
      </form>
    </details>
  );
}

// ═══════════════════════════════════════════════════════════
// Interaction popup (channel / payment / route-pay)
// ═══════════════════════════════════════════════════════════

function InteractionPopup({
  interaction, interactionDeposit, setInteractionDeposit,
  interactionAmount, setInteractionAmount,
  interactionLoading, onClose,
  onOpenChannel, onSendPayment, onRoutePayment, onSwitchToRoutePay, onSwitchToChannel,
  lbl, allAgents,
}: {
  interaction: { mode: "channel" | "payment" | "route-pay"; sourceAgent?: AgentState; targetAgent?: AgentState; channelId?: string };
  interactionDeposit: string; setInteractionDeposit: (v: string) => void;
  interactionAmount: string; setInteractionAmount: (v: string) => void;
  interactionLoading: boolean;
  onClose: () => void;
  onOpenChannel: () => void;
  onSendPayment: () => void;
  onRoutePayment: () => void;
  onSwitchToRoutePay: () => void;
  onSwitchToChannel: () => void;
  lbl: (a: AgentState) => string;
  allAgents: AgentState[];
}) {
  const closeBtn = (
    <button onClick={onClose} className="text-text-muted hover:text-text-primary transition-colors">
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" /></svg>
    </button>
  );

  const arrow = (
    <svg className="w-4 h-4 text-text-muted shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5 21 12m0 0-7.5 7.5M21 12H3" /></svg>
  );

  if (interaction.mode === "channel") {
    return (
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-semibold text-text-primary">Open Channel</h3>
          {closeBtn}
        </div>
        <div className="flex items-center gap-2 text-[11px]">
          <span className="font-medium text-text-primary">{lbl(interaction.sourceAgent!)}</span>
          {arrow}
          <span className="font-medium text-text-primary">{lbl(interaction.targetAgent!)}</span>
        </div>
        <div>
          <label className="text-[10px] font-medium text-text-secondary block mb-1">Deposit (wei)</label>
          <input value={interactionDeposit} onChange={(e) => setInteractionDeposit(e.target.value)} type="number" min="1"
            className="w-full h-8 bg-surface-overlay border border-border rounded-lg px-3 text-xs font-mono text-text-primary placeholder:text-text-muted focus-ring" />
        </div>

        <Button onClick={onOpenChannel} disabled={interactionLoading} size="sm" className="w-full h-8 text-xs">
          {interactionLoading ? "Connecting & Opening..." : "Open Channel"}
        </Button>
      </div>
    );
  }

  if (interaction.mode === "payment") {
    const ch = interaction.sourceAgent?.channels.find((c) => c.channel_id === interaction.channelId);
    const receiverAgent = ch ? allAgents.find((a) => a.identity?.eth_address === ch.receiver) : null;
    return (
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-semibold text-text-primary">Send Payment</h3>
          {closeBtn}
        </div>
        <div className="flex items-center gap-2 text-[11px]">
          <span className="font-medium text-text-primary">{lbl(interaction.sourceAgent!)}</span>
          {arrow}
          <span className="font-medium text-text-primary">{receiverAgent ? lbl(receiverAgent) : "Peer"}</span>
          <span className="ml-auto text-[9px] font-mono text-text-muted">{ch ? `${formatWei(ch.remaining_balance)} left` : ""}</span>
        </div>
        <div>
          <label className="text-[10px] font-medium text-text-secondary block mb-1">Amount (wei)</label>
          <input value={interactionAmount} onChange={(e) => setInteractionAmount(e.target.value)} type="number" min="1"
            className="w-full h-8 bg-surface-overlay border border-border rounded-lg px-3 text-xs font-mono text-text-primary placeholder:text-text-muted focus-ring" />
        </div>

        <Button onClick={onSendPayment} disabled={interactionLoading} variant="secondary" size="sm" className="w-full h-8 text-xs bg-success/80 hover:bg-success text-white">
          {interactionLoading ? "Sending..." : "Send Direct Payment"}
        </Button>
      </div>
    );
  }

  // route-pay mode
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <h3 className="text-xs font-semibold text-text-primary">Route Payment</h3>
          <span className="text-[8px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-warning/15 text-warning">Multi-hop</span>
        </div>
        {closeBtn}
      </div>
      <div className="flex items-center gap-2 text-[11px]">
        <span className="font-medium text-text-primary">{lbl(interaction.sourceAgent!)}</span>
        <svg className="w-4 h-4 text-warning shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5 21 12m0 0-7.5 7.5M21 12H3" />
        </svg>
        <span className="text-[9px] text-warning font-mono">···</span>
        <svg className="w-4 h-4 text-warning shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5 21 12m0 0-7.5 7.5M21 12H3" />
        </svg>
        <span className="font-medium text-text-primary">{lbl(interaction.targetAgent!)}</span>
      </div>
      <p className="text-[9px] text-text-muted leading-relaxed">
        No direct channel. Payment will be routed through intermediate nodes using HTLC forwarding.
      </p>
      <div>
        <label className="text-[10px] font-medium text-text-secondary block mb-1">Amount (wei)</label>
        <input value={interactionAmount} onChange={(e) => setInteractionAmount(e.target.value)} type="number" min="1"
          className="w-full h-8 bg-surface-overlay border border-border rounded-lg px-3 text-xs font-mono text-text-primary placeholder:text-text-muted focus-ring" />
      </div>
      <Button onClick={onRoutePayment} disabled={interactionLoading} variant="secondary" size="sm" className="w-full h-8 text-xs bg-warning/80 hover:bg-warning text-black font-semibold">
        {interactionLoading ? "Routing..." : "Route Payment (HTLC)"}
      </Button>
      <button onClick={onSwitchToChannel} className="w-full text-center text-[9px] text-accent/70 hover:text-accent transition-colors pt-0.5">
        or open a direct channel instead →
      </button>
    </div>
  );
}


// ═══════════════════════════════════════════════════════════
// Simulation Panel
// ═══════════════════════════════════════════════════════════

type SimPhase = "idle" | "spawning" | "connecting" | "simulating" | "done";
type SimSpeed = "slow" | "normal" | "fast" | "turbo";
const SPEED_CONFIG: Record<SimSpeed, { spawnDelay: number; channelDelay: number; payDelay: number; animateEvery: number; channelBatch: number; payBatch: number }> = {
  slow:   { spawnDelay: 1500, channelDelay: 400, payDelay: 600,  animateEvery: 1,  channelBatch: 1, payBatch: 1  },
  normal: { spawnDelay: 1000, channelDelay: 150, payDelay: 200,  animateEvery: 3,  channelBatch: 2, payBatch: 2  },
  fast:   { spawnDelay: 800,  channelDelay: 50,  payDelay: 50,   animateEvery: 10, channelBatch: 4, payBatch: 5  },
  turbo:  { spawnDelay: 600,  channelDelay: 0,   payDelay: 0,    animateEvery: 50, channelBatch: 8, payBatch: 10 },
};

function SimulationPanel({
  manager, allAgents, onlineAgents, lbl, agentLabel,
  setLoadingNodes, setAnimatingRoute, collectKnownChannels, pushEvent,
  agentNames, setAgentNames, getAgents,
}: {
  manager: ReturnType<typeof useAgentManager>;
  allAgents: AgentState[];
  onlineAgents: AgentState[];
  lbl: (a: AgentState) => string;
  agentLabel: (i: number) => string;
  setLoadingNodes: React.Dispatch<React.SetStateAction<LoadingNode[]>>;
  setAnimatingRoute: React.Dispatch<React.SetStateAction<AnimatingRoute | null>>;
  collectKnownChannels: () => { channel_id: string; peer_a: string; peer_b: string; capacity: number }[];
  pushEvent: (e: Omit<NetworkEvent, "id" | "timestamp">) => void;
  agentNames: Map<number, string>;
  setAgentNames: React.Dispatch<React.SetStateAction<Map<number, string>>>;
  getAgents: () => AgentState[];
}) {
  const [nodeCount, setNodeCount] = useState("4");
  const [deposit, setDeposit] = useState("5000000");
  const [paymentRounds, setPaymentRounds] = useState("10");
  const [minPay, setMinPay] = useState("10000");
  const [maxPay, setMaxPay] = useState("500000");
  const [phase, setPhase] = useState<SimPhase>("idle");
  const [progress, setProgress] = useState("");
  const [topology, setTopology] = useState<"ring" | "mesh" | "random">("ring");
  const [speed, setSpeed] = useState<SimSpeed>("normal");
  const cancelRef = useRef(false);
  const [editingNames, setEditingNames] = useState(false);
  const [stats, setStats] = useState({ ok: 0, fail: 0, total: 0 });

  const sleep = (ms: number) => ms > 0 ? new Promise((r) => setTimeout(r, ms)) : Promise.resolve();
  const randInt = (min: number, max: number) => Math.floor(Math.random() * (max - min + 1)) + min;

  // Resolve multiaddr helper
  const resolveAddr = (agent: AgentState) => {
    const addrs = agent.identity?.addrs ?? [];
    const tcp = addrs.find((a) => a.includes("/tcp/") && !a.includes("/ws"));
    if (!tcp) return null;
    const addr = tcp.replace("/ip4/0.0.0.0/", "/ip4/127.0.0.1/");
    return addr.includes("/p2p/") ? addr : `${addr}/p2p/${agent.identity!.peer_id}`;
  };

  const runSimulation = async () => {
    cancelRef.current = false;
    const count = parseInt(nodeCount);
    const dep = parseInt(deposit);
    const rounds = parseInt(paymentRounds);
    const lo = parseInt(minPay);
    const hi = parseInt(maxPay);
    const cfg = SPEED_CONFIG[speed];

    if (isNaN(count) || count < 2 || count > 50) return;
    if (isNaN(dep) || dep < 1000) return;
    if (isNaN(rounds) || rounds < 1) return;

    setStats({ ok: 0, fail: 0, total: 0 });

    // ── Phase 1: Spawn nodes ──
    setPhase("spawning");
    const needed = count - manager.agents.length;
    if (needed > 0) {
      for (let i = 0; i < needed; i++) {
        if (cancelRef.current) { setPhase("idle"); return; }
        setProgress(`Spawning ${i + 1}/${needed}`);
        await manager.startAgent();
        await sleep(cfg.spawnDelay);
      }
      setProgress("Waiting for nodes...");
      // Poll until enough agents are online or timeout
      const deadline = Date.now() + 15000;
      while (getAgents().filter((a) => a.online).length < count && Date.now() < deadline) {
        await manager.refresh();
        await sleep(500);
      }
    }
    const readyCount = getAgents().filter((a) => a.online && a.identity?.peer_id).length;
    setProgress(`${Math.min(count, readyCount)} nodes ready`);

    // ── Phase 2: Open channels ──
    setPhase("connecting");
    await manager.refresh();
    await sleep(300);

    // Use fresh agents from ref — onlineAgents may be stale in this closure
    let agents = getAgents().filter((a) => a.online && a.identity?.peer_id);
    if (agents.length < 2) { setPhase("idle"); setProgress("Not enough agents"); return; }

    // Build topology pairs
    const pairs: [number, number][] = [];
    if (topology === "ring") {
      for (let i = 0; i < agents.length; i++) pairs.push([i, (i + 1) % agents.length]);
    } else if (topology === "mesh") {
      for (let i = 0; i < agents.length; i++)
        for (let j = i + 1; j < agents.length; j++) pairs.push([i, j]);
    } else {
      const seen = new Set<string>();
      for (let i = 0; i < agents.length; i++) {
        const n = randInt(1, Math.min(2, agents.length - 1));
        for (let c = 0; c < n; c++) {
          let j = randInt(0, agents.length - 1);
          while (j === i) j = randInt(0, agents.length - 1);
          const k = `${Math.min(i, j)}-${Math.max(i, j)}`;
          if (!seen.has(k)) { seen.add(k); pairs.push([i, j]); }
        }
      }
    }

    // Filter out already-existing channels
    const todo = pairs.filter(([si, ri]) => {
      const s = agents[si], r = agents[ri];
      if (!s?.identity?.peer_id || !r?.identity?.peer_id || !r?.identity?.eth_address) return false;
      return !s.channels.some(
        (c) => c.state === "ACTIVE" && c.sender === s.identity?.eth_address && c.peer_id === r.identity?.peer_id
      );
    });

    // Open channels in batches
    for (let b = 0; b < todo.length; b += cfg.channelBatch) {
      if (cancelRef.current) { setPhase("idle"); return; }
      const batch = todo.slice(b, b + cfg.channelBatch);
      setProgress(`Channels ${b + 1}-${Math.min(b + cfg.channelBatch, todo.length)}/${todo.length}`);

      const promises = batch.map(async ([si, ri]) => {
        const sender = agents[si], receiver = agents[ri];
        const full = resolveAddr(receiver);
        if (full) try { await sender.api.connectPeer(full); } catch {}
        try {
          await sender.api.openChannel(receiver.identity!.peer_id!, receiver.identity!.eth_address!, dep);
        } catch {}
      });
      await Promise.allSettled(promises);
      if (cfg.channelDelay > 0) await sleep(cfg.channelDelay);
    }

    // Refresh all agents and wait for state to propagate
    for (const a of agents) a.refresh();
    pushEvent({ type: "channel_open", from: "Sim", message: `Opened ${todo.length} channels (${topology})`, meta: `Deposit: ${dep.toLocaleString()} wei each` });
    await sleep(1500); // Wait for WS/poll to deliver updated channel data

    // ── Phase 3: Run payments ──
    setPhase("simulating");

    // Re-snapshot agents with fresh channel data
    agents = getAgents().filter((a) => a.online && a.identity?.peer_id);
    let knownChannels = collectKnownChannels();
    let okCount = 0, failCount = 0;
    const refreshKnownEvery = Math.max(20, Math.floor(rounds / 5));

    for (let r = 0; r < rounds;) {
      if (cancelRef.current) { setPhase("idle"); return; }

      // Periodically refresh known channels and agent state for routing
      if (r > 0 && r % refreshKnownEvery === 0) {
        for (const a of agents) a.refresh();
        await sleep(300);
        agents = getAgents().filter((a) => a.online && a.identity?.peer_id);
        knownChannels = collectKnownChannels();
      }

      // Build a batch of payments
      const batchSize = Math.min(cfg.payBatch, rounds - r);
      const batchPromises: Promise<boolean>[] = [];

      for (let bi = 0; bi < batchSize; bi++) {
        const amount = randInt(lo, hi);
        const ri = r + bi;

        // Pick random sender with balance
        const eligible = agents.filter((a) =>
          a.channels.some((c) => c.state === "ACTIVE" && c.sender === a.identity?.eth_address && c.remaining_balance > amount)
        );
        if (eligible.length === 0) {
          batchPromises.push(Promise.resolve(false));
          continue;
        }

        const sender = eligible[randInt(0, eligible.length - 1)];
        const senderPid = sender.identity?.peer_id;
        const directChs = sender.channels.filter(
          (c) => c.state === "ACTIVE" && c.sender === sender.identity?.eth_address && c.remaining_balance > amount
        );
        const useDirect = directChs.length > 0 && (Math.random() < 0.6 || agents.length <= 2);

        // Animate only every Nth payment
        const shouldAnimate = ri % cfg.animateEvery === 0;

        if (useDirect) {
          const ch = directChs[randInt(0, directChs.length - 1)];
          const recvAgent = agents.find((a) => a.identity?.eth_address === ch.receiver);
          const rPid = recvAgent?.identity?.peer_id;

          if (shouldAnimate && senderPid && rPid) {
            setLoadingNodes([{ peerId: senderPid, color: STATUS_EXECUTING }, { peerId: rPid, color: STATUS_EXECUTING }]);
            setAnimatingRoute({ hops: [senderPid, rPid], color: STATUS_EXECUTING, type: "payment" });
          }

          batchPromises.push(
            sender.api.sendPayment(ch.channel_id, amount).then(() => true, () => false)
          );
        } else {
          const others = agents.filter((a) => a.identity?.peer_id !== senderPid && a.identity?.peer_id);
          if (others.length === 0) { batchPromises.push(Promise.resolve(false)); continue; }
          const receiver = others[randInt(0, others.length - 1)];
          const rPid = receiver.identity!.peer_id!;

          if (shouldAnimate && senderPid) {
            setLoadingNodes([{ peerId: senderPid, color: STATUS_EXECUTING }, { peerId: rPid, color: STATUS_EXECUTING }]);
            setAnimatingRoute({ hops: [senderPid, rPid], color: STATUS_EXECUTING, type: "payment" });
          }

          batchPromises.push(
            sender.api.routePayment(rPid, amount, knownChannels).then(() => true, () => false)
          );
        }
      }

      const results = await Promise.allSettled(batchPromises);
      for (const res of results) {
        if (res.status === "fulfilled" && res.value) okCount++;
        else failCount++;
      }

      r += batchSize;
      setStats({ ok: okCount, fail: failCount, total: r });
      setProgress(`${r}/${rounds} — ${okCount} ok, ${failCount} fail`);

      // Push event every 10th batch so the events panel shows progress
      if (r % (cfg.payBatch * 10) === 0 || r === rounds) {
        pushEvent({ type: "payment", from: "Sim", message: `Progress: ${okCount} ok / ${failCount} fail (${r}/${rounds})` });
      }

      if (cfg.payDelay > 0) await sleep(cfg.payDelay);
    }

    setLoadingNodes([]);
    setAnimatingRoute(null);
    // Refresh all agents once at the end
    for (const a of agents) a.refresh();

    setPhase("done");
    setProgress(`Done: ${okCount} ok, ${failCount} fail / ${rounds} total`);
    pushEvent({ type: "payment", from: "Sim", message: `Simulation: ${okCount} payments ok, ${failCount} failed out of ${rounds}` });
  };

  const isRunning = phase === "spawning" || phase === "connecting" || phase === "simulating";

  return (
    <div className="rounded-lg border border-accent/20 bg-accent/[0.03] p-3 space-y-2.5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <h4 className="text-[10px] font-semibold uppercase tracking-widest text-accent">Simulation</h4>
          {isRunning && <span className="w-2 h-2 rounded-full bg-accent animate-pulse" />}
        </div>
        {isRunning && (
          <Badge variant="outline" className="text-[8px] border-accent/30 text-accent animate-pulse">Running</Badge>
        )}
      </div>

      {/* Agent Naming */}
      <details open={editingNames} onToggle={(e) => setEditingNames((e.target as HTMLDetailsElement).open)}>
        <summary className="text-[9px] font-semibold uppercase tracking-widest text-text-muted cursor-pointer hover:text-text-secondary transition-colors">
          Agent Names
        </summary>
        <div className="mt-1.5 space-y-1">
          {allAgents.map((a, i) => {
            const port = manager.agents[i]?.apiPort ?? 8080 + i;
            return (
              <div key={i} className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: NODE_NEUTRAL }} />
                <input
                  className="flex-1 h-5 bg-surface-overlay border border-border rounded px-1.5 text-[10px] font-mono text-text-primary focus-ring"
                  value={agentNames.get(port) ?? agentLabel(i)}
                  onChange={(e) => setAgentNames((prev) => new Map(prev).set(port, e.target.value))}
                  placeholder={agentLabel(i)}
                />
                <span className="text-[8px] text-text-muted font-mono">:{port}</span>
              </div>
            );
          })}
          {allAgents.length === 0 && <p className="text-[9px] text-text-muted italic">No agents running</p>}
        </div>
      </details>

      {/* Controls */}
      <div className="space-y-3">
        <div className="grid grid-cols-3 gap-2">
          <div>
            <Label htmlFor="sim-nodes" className="text-[9px] text-text-muted mb-1 block">Nodes</Label>
            <Input id="sim-nodes" value={nodeCount} onChange={(e) => setNodeCount(e.target.value)} type="number" min="2" max="50" disabled={isRunning}
              className="h-7 text-[11px] font-mono bg-surface-overlay border-border" />
          </div>
          <div>
            <Label htmlFor="sim-topo" className="text-[9px] text-text-muted mb-1 block">Topology</Label>
            <Select value={topology} onValueChange={(v) => setTopology(v as typeof topology)} disabled={isRunning}>
              <SelectTrigger id="sim-topo" size="sm" className="w-full h-7 text-[11px] bg-surface-overlay border-border">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="ring">Ring</SelectItem>
                <SelectItem value="mesh">Mesh</SelectItem>
                <SelectItem value="random">Random</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label htmlFor="sim-speed" className="text-[9px] text-text-muted mb-1 block">Speed</Label>
            <Select value={speed} onValueChange={(v) => setSpeed(v as SimSpeed)} disabled={isRunning}>
              <SelectTrigger id="sim-speed" size="sm" className="w-full h-7 text-[11px] bg-surface-overlay border-border">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="slow">Slow</SelectItem>
                <SelectItem value="normal">Normal</SelectItem>
                <SelectItem value="fast">Fast</SelectItem>
                <SelectItem value="turbo">Turbo</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div>
            <Label htmlFor="sim-deposit" className="text-[9px] text-text-muted mb-1 block">Deposit/ch</Label>
            <Input id="sim-deposit" value={deposit} onChange={(e) => setDeposit(e.target.value)} type="number" min="1000" disabled={isRunning}
              className="h-7 text-[11px] font-mono bg-surface-overlay border-border" />
          </div>
          <div>
            <Label htmlFor="sim-rounds" className="text-[9px] text-text-muted mb-1 block">Rounds</Label>
            <Input id="sim-rounds" value={paymentRounds} onChange={(e) => setPaymentRounds(e.target.value)} type="number" min="1" max="10000" disabled={isRunning}
              className="h-7 text-[11px] font-mono bg-surface-overlay border-border" />
          </div>
        </div>

        <div>
          <div className="flex items-center justify-between mb-1.5">
            <Label className="text-[9px] text-text-muted">Payment Range</Label>
            <span className="text-[9px] font-mono text-text-muted tabular-nums">{parseInt(minPay).toLocaleString()} — {parseInt(maxPay).toLocaleString()} wei</span>
          </div>
          <div className="flex items-center gap-2">
            <Input value={minPay} onChange={(e) => setMinPay(e.target.value)} type="number" min="1" disabled={isRunning} placeholder="Min"
              className="h-7 w-24 text-[11px] font-mono bg-surface-overlay border-border" />
            <Slider
              value={[parseInt(minPay) || 0, parseInt(maxPay) || 500000]}
              onValueChange={([lo, hi]) => { setMinPay(String(lo)); setMaxPay(String(hi)); }}
              min={1000}
              max={1000000}
              step={10000}
              disabled={isRunning}
              className="flex-1"
            />
            <Input value={maxPay} onChange={(e) => setMaxPay(e.target.value)} type="number" min="1" disabled={isRunning} placeholder="Max"
              className="h-7 w-24 text-[11px] font-mono bg-surface-overlay border-border" />
          </div>
        </div>
      </div>

      {/* Progress + stats */}
      {progress && (
        <div className={`text-[10px] px-2.5 py-1.5 rounded-md font-mono ${
          phase === "done" ? "bg-success/10 text-success border border-success/20" :
          phase === "idle" ? "bg-surface-overlay text-text-muted border border-border" :
          "bg-accent/10 text-accent border border-accent/20"
        }`}>
          {progress}
        </div>
      )}
      {stats.total > 0 && (
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="text-[9px] font-mono border-success/30" style={{ color: STATUS_COMPLETED }}>
            {stats.ok} ok
          </Badge>
          <Badge variant="outline" className="text-[9px] font-mono border-purple-500/30" style={{ color: STATUS_FAILED }}>
            {stats.fail} fail
          </Badge>
          <span className="text-[9px] font-mono text-text-muted ml-auto tabular-nums">{stats.total}/{paymentRounds}</span>
        </div>
      )}

      {/* Action buttons */}
      <div className="flex gap-2">
        <Button onClick={runSimulation} disabled={isRunning} size="sm"
          className="flex-1 h-8 text-[11px] bg-accent/90 hover:bg-accent text-white font-semibold">
          {phase === "spawning" ? "Spawning..." :
           phase === "connecting" ? "Connecting..." :
           phase === "simulating" ? "Running..." :
           phase === "done" ? "Run Again" : "Run Simulation"}
        </Button>
        {isRunning && (
          <Button onClick={() => { cancelRef.current = true; }} variant="outline" size="sm"
            className="h-8 text-[11px] text-danger border-danger/30 hover:bg-danger/10 font-medium">
            Stop
          </Button>
        )}
      </div>
    </div>
  );
}
