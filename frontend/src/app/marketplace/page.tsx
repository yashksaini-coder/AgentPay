"use client";

import { useEffect, useState, useCallback } from "react";
import {
  createApi,
  formatWei,
  type DiscoveredAgent,
  type GatedResource,
  type PeerReputation,
  type Balance,
  type Channel,
} from "@/lib/api";
import TrustBadge from "@/components/TrustBadge";
import PaymentModal from "@/components/PaymentModal";
import { BlurFade } from "@/components/ui/blur-fade";
import { BorderBeam } from "@/components/ui/border-beam";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Search,
  RefreshCw,
  Zap,
  ExternalLink,
  Globe,
  Shield,
  CircleDollarSign,
  Handshake,
  Network,
  Lock,
  BarChart3,
  Clock,
  Layers,
  ArrowUpDown,
  Wallet,
} from "lucide-react";

function shortenId(id: string, n = 8): string {
  if (!id || id.length <= n * 2 + 3) return id;
  return `${id.slice(0, n)}...${id.slice(-n)}`;
}

const PROTOCOL_SERVICES = [
  {
    icon: CircleDollarSign,
    name: "Payment Channels",
    desc: "Open off-chain channels with cumulative vouchers. Sub-millisecond micropayments.",
    tag: "Core",
    color: "text-emerald-400",
    bg: "bg-emerald-500/8",
    border: "border-emerald-500/15",
  },
  {
    icon: Lock,
    name: "x402 Gateway",
    desc: "Payment-gated API endpoints. Agents pay per-call to access services.",
    tag: "Gateway",
    color: "text-amber-400",
    bg: "bg-amber-500/8",
    border: "border-amber-500/15",
  },
  {
    icon: Handshake,
    name: "Price Negotiation",
    desc: "Automated multi-round negotiation. Counter-offers, acceptance, rejection.",
    tag: "Protocol",
    color: "text-violet-400",
    bg: "bg-violet-500/8",
    border: "border-violet-500/15",
  },
  {
    icon: Shield,
    name: "Trust & Reputation",
    desc: "Dynamic trust scores from payment history. Discounts for reliable peers.",
    tag: "Trust",
    color: "text-cyan-400",
    bg: "bg-cyan-500/8",
    border: "border-cyan-500/15",
  },
  {
    icon: BarChart3,
    name: "SLA Enforcement",
    desc: "Latency monitoring, violation detection, automatic dispute filing.",
    tag: "SLA",
    color: "text-rose-400",
    bg: "bg-rose-500/8",
    border: "border-rose-500/15",
  },
  {
    icon: Layers,
    name: "Multi-Chain Settle",
    desc: "Settle on Ethereum, Algorand, or Filecoin FEVM. Choose at runtime.",
    tag: "Chain",
    color: "text-blue-400",
    bg: "bg-blue-500/8",
    border: "border-blue-500/15",
  },
];

/** Enriched agent with balance and channel data from its own API port */
interface EnrichedAgent {
  peer_id: string;
  eth_address: string;
  capabilities: DiscoveredAgent["capabilities"];
  addrs: string[];
  label: string;
  apiPort: number;
  balance: Balance | null;
  channels: Channel[];
  connectedPeers: number;
}

interface RunningNode {
  apiPort: number;
  label: string;
  alive: boolean;
  url?: string; // set in remote mode
  peer_id?: string; // set when discovered via /discovery/agents
}

export default function MarketplacePage() {
  const [enrichedAgents, setEnrichedAgents] = useState<EnrichedAgent[]>([]);
  const [resources, setResources] = useState<GatedResource[]>([]);
  const [reputations, setReputations] = useState<Map<string, PeerReputation>>(new Map());
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [payingResource, setPayingResource] = useState<GatedResource | null>(null);

  const apiBase = (() => {
    const env = process.env.NEXT_PUBLIC_API_URL;
    if (env && env !== "/api") return env;
    return "http://127.0.0.1:8080";
  })();

  /** Build the API URL for a node — remote uses the single env URL, local uses port. */
  const nodeUrl = useCallback((node: RunningNode): string => {
    if (node.url) return node.url; // remote mode
    return `http://127.0.0.1:${node.apiPort}`;
  }, []);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const nodesRes = await fetch("/api/agents").then((r) => r.json()).catch(() => ({ agents: [] }));
      const runningNodes: RunningNode[] = nodesRes.agents || [];
      const isRemoteMode = runningNodes.length > 0 && !!runningNodes[0].url;

      const allAgents: EnrichedAgent[] = [];
      const allResources: GatedResource[] = [];
      const repMap = new Map<string, PeerReputation>();

      if (isRemoteMode && runningNodes.length > 1) {
        // Remote mode with multiple discovered agents:
        // Fetch shared data once from the single backend, then map discovery data per agent.
        const api = createApi(nodeUrl(runningNodes[0]));
        const [balRes, chRes, peersRes, discRes, gwRes, repRes] = await Promise.allSettled([
          api.getBalance(),
          api.getChannels(),
          api.getPeers(),
          api.getDiscoveredAgents(),
          api.getGatewayResources(),
          api.getReputation(),
        ]);

        const discoveredMap = new Map<string, DiscoveredAgent>();
        if (discRes.status === "fulfilled") {
          for (const a of discRes.value.agents || []) {
            discoveredMap.set(a.peer_id, a);
          }
        }

        // The first node (Agent A) is the real running node — give it live data
        // Other nodes get their discovery data with empty balance/channels
        for (const node of runningNodes) {
          const disc = node.peer_id ? discoveredMap.get(node.peer_id) : undefined;
          const isMainNode = node === runningNodes[0];

          allAgents.push({
            peer_id: node.peer_id || disc?.peer_id || "",
            eth_address: disc?.eth_address || "",
            capabilities: disc?.capabilities || [],
            addrs: disc?.addrs || [],
            label: node.label,
            apiPort: node.apiPort,
            balance: isMainNode && balRes.status === "fulfilled" ? balRes.value : null,
            channels: isMainNode && chRes.status === "fulfilled" ? chRes.value.channels : [],
            connectedPeers: isMainNode && peersRes.status === "fulfilled" ? (peersRes.value.connected ?? 0) : 0,
          });
        }

        if (gwRes.status === "fulfilled") {
          for (const r of gwRes.value.resources || []) {
            if (!allResources.some((x) => x.path === r.path)) allResources.push(r);
          }
        }
        if (repRes.status === "fulfilled") {
          for (const p of repRes.value.peers || []) {
            if (!repMap.has(p.peer_id)) repMap.set(p.peer_id, p);
          }
        }
      } else {
        // Local mode or single remote agent: fetch per-node data
        await Promise.all(
          runningNodes.map(async (node) => {
            const api = createApi(nodeUrl(node));

            const [identityRes, balRes, chRes, peersRes, discRes, gwRes, repRes] = await Promise.allSettled([
              api.getIdentity(),
              api.getBalance(),
              api.getChannels(),
              api.getPeers(),
              api.getDiscoveredAgents(),
              api.getGatewayResources(),
              api.getReputation(),
            ]);

            if (identityRes.status === "fulfilled" && identityRes.value.peer_id) {
              const id = identityRes.value;
              let caps: DiscoveredAgent["capabilities"] = [];
              if (discRes.status === "fulfilled") {
                for (const a of discRes.value.agents || []) {
                  if (a.peer_id === id.peer_id && a.capabilities?.length) {
                    caps = a.capabilities;
                  }
                }
              }

              allAgents.push({
                peer_id: id.peer_id!,
                eth_address: id.eth_address || "",
                capabilities: caps,
                addrs: id.addrs || [],
                label: node.label,
                apiPort: node.apiPort,
                balance: balRes.status === "fulfilled" ? balRes.value : null,
                channels: chRes.status === "fulfilled" ? chRes.value.channels : [],
                connectedPeers: peersRes.status === "fulfilled" ? (peersRes.value.connected ?? 0) : 0,
              });
            }

            if (gwRes.status === "fulfilled") {
              for (const r of gwRes.value.resources || []) {
                if (!allResources.some((x) => x.path === r.path)) allResources.push(r);
              }
            }

            if (repRes.status === "fulfilled") {
              for (const p of repRes.value.peers || []) {
                if (!repMap.has(p.peer_id)) repMap.set(p.peer_id, p);
              }
            }
          })
        );
      }

      setEnrichedAgents(allAgents);
      setResources(allResources);
      setReputations(repMap);
    } catch {
      // Backend may not be running
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const load = async () => { if (!cancelled) await fetchData(); };
    load();
    return () => { cancelled = true; };
  }, [fetchData]);

  const filteredAgents = enrichedAgents.filter((a) => {
    if (!search) return true;
    const s = search.toLowerCase();
    return (
      a.peer_id?.toLowerCase().includes(s) ||
      a.label.toLowerCase().includes(s) ||
      a.capabilities?.some((c) => c.service_type.toLowerCase().includes(s))
    );
  });

  // Aggregate stats
  const totalChannels = enrichedAgents.reduce((s, a) => s + a.channels.length, 0);
  const activeChannels = enrichedAgents.reduce(
    (s, a) => s + a.channels.filter((c) => c.state === "ACTIVE").length, 0
  );
  const totalDeposited = enrichedAgents.reduce((s, a) => s + (a.balance?.total_deposited ?? 0), 0);
  const totalPaid = enrichedAgents.reduce((s, a) => s + (a.balance?.total_paid ?? 0), 0);
  const totalPeers = enrichedAgents.reduce((s, a) => s + a.connectedPeers, 0);

  return (
    <div className="min-h-screen pt-8 pb-16 px-4">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <BlurFade delay={0}>
          <div className="flex items-start justify-between mb-8">
            <div>
              <p className="text-[11px] font-semibold tracking-[0.2em] uppercase text-accent mb-2">
                Marketplace
              </p>
              <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-text-primary">
                Agent Services
              </h1>
              <p className="text-sm text-text-muted mt-1.5 max-w-lg">
                Discover agents on the network, browse payment-gated services, and negotiate terms — all peer-to-peer.
              </p>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={fetchData}
              disabled={loading}
              className="text-xs border-white/[0.08] text-text-muted hover:text-text-primary hover:bg-white/[0.04] mt-1"
            >
              <RefreshCw className={`w-3 h-3 mr-1.5 ${loading ? "animate-spin" : ""}`} />
              Refresh
            </Button>
          </div>
        </BlurFade>

        {/* Stats bar */}
        <BlurFade delay={0.05}>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-8">
            {[
              { icon: Network, label: "Agents Online", value: enrichedAgents.length.toString(), color: "text-emerald-400" },
              { icon: ArrowUpDown, label: "Active Channels", value: `${activeChannels}/${totalChannels}`, color: "text-accent" },
              { icon: Wallet, label: "Total Deposited", value: formatWei(totalDeposited), color: "text-amber-400" },
              { icon: CircleDollarSign, label: "Total Paid", value: formatWei(totalPaid), color: "text-cyan-400" },
              { icon: Shield, label: "Connected Peers", value: totalPeers.toString(), color: "text-violet-400" },
              { icon: Globe, label: "Gated Services", value: resources.length.toString(), color: "text-rose-400" },
            ].map((stat) => (
              <div
                key={stat.label}
                className="flex items-center gap-2.5 px-3.5 py-3 rounded-xl border border-white/[0.06] bg-white/[0.015]"
              >
                <stat.icon className={`w-3.5 h-3.5 ${stat.color} shrink-0`} />
                <div className="min-w-0">
                  <div className="text-sm font-bold text-text-primary tabular-nums leading-none truncate">
                    {stat.value}
                  </div>
                  <div className="text-[9px] text-text-muted mt-0.5 truncate">{stat.label}</div>
                </div>
              </div>
            ))}
          </div>
        </BlurFade>

        {/* Search */}
        <BlurFade delay={0.08}>
          <div className="relative mb-10">
            <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-text-muted" />
            <Input
              placeholder="Search by peer ID, label, or capability..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-10 h-10 text-sm bg-white/[0.02] border-white/[0.06] rounded-xl focus:border-accent/30"
            />
          </div>
        </BlurFade>

        {/* Gateway Resources */}
        {resources.length > 0 && (
          <div className="mb-12">
            <BlurFade delay={0.1}>
              <h2 className="text-sm font-semibold text-text-secondary mb-4 flex items-center gap-2">
                <Globe className="w-3.5 h-3.5 text-accent" />
                Payment-Gated Endpoints
                <Badge variant="outline" className="text-[9px] font-mono border-accent/20 text-accent ml-1">
                  x402
                </Badge>
              </h2>
            </BlurFade>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {resources.map((res, i) => (
                <BlurFade key={res.path} delay={0.05 * i} inView>
                  <div className="group relative rounded-2xl border border-white/[0.06] bg-white/[0.015] p-5 transition-all duration-300 hover:border-white/[0.12] hover:bg-white/[0.025] overflow-hidden">
                    <div className="flex items-center justify-between mb-3">
                      <code className="text-xs font-mono text-accent font-medium">{res.path}</code>
                      <Badge variant="outline" className="text-[9px] font-mono border-amber-500/20 text-amber-400">
                        {formatWei(res.price)}
                      </Badge>
                    </div>
                    <p className="text-[12px] text-text-muted mb-4 leading-relaxed">
                      {res.description || "Payment-gated endpoint"}
                    </p>
                    <Button
                      size="sm"
                      className="w-full h-8 text-[11px] font-medium bg-accent/10 hover:bg-accent/18 text-accent border border-accent/15 rounded-lg transition-colors"
                      onClick={() => setPayingResource(res)}
                    >
                      <CircleDollarSign className="w-3 h-3 mr-1.5" />
                      Pay & Access
                    </Button>
                    <BorderBeam
                      size={180}
                      duration={8}
                      colorFrom="#7c6df0"
                      colorTo="transparent"
                      className="opacity-0 group-hover:opacity-100 transition-opacity"
                    />
                  </div>
                </BlurFade>
              ))}
            </div>
          </div>
        )}

        {/* Agents */}
        <div className="mb-12">
          <BlurFade delay={0.1}>
            <h2 className="text-sm font-semibold text-text-secondary mb-4 flex items-center gap-2">
              <Network className="w-3.5 h-3.5 text-emerald-400" />
              Network Agents
              <span className="text-[10px] font-mono text-text-muted ml-1">
                ({filteredAgents.length})
              </span>
            </h2>
          </BlurFade>

          {loading && filteredAgents.length === 0 ? (
            <div className="text-center py-16 text-text-muted">
              <RefreshCw className="w-5 h-5 mx-auto mb-3 animate-spin opacity-30" />
              <p className="text-xs">Discovering agents on the network...</p>
            </div>
          ) : filteredAgents.length === 0 ? (
            <BlurFade delay={0.15}>
              <div className="text-center py-16 rounded-2xl border border-white/[0.04] bg-white/[0.01]">
                <Network className="w-6 h-6 mx-auto mb-3 text-text-muted/30" />
                <p className="text-sm text-text-muted mb-1">No agents discovered yet</p>
                <p className="text-xs text-text-muted/60">
                  Start backend agents with <code className="text-accent">./scripts/dev.sh</code>
                </p>
              </div>
            </BlurFade>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {filteredAgents.map((agent, i) => {
                const rep = reputations.get(agent.peer_id);
                const trust = rep
                  ? Math.min(1, rep.payments_sent / Math.max(1, rep.payments_sent + rep.payments_failed))
                  : 0;
                const activeCount = agent.channels.filter((c) => c.state === "ACTIVE").length;
                const deposited = agent.balance?.total_deposited ?? 0;
                const remaining = agent.balance?.total_remaining ?? 0;
                const paidAmt = agent.balance?.total_paid ?? 0;
                const usagePct = deposited > 0 ? Math.round((remaining / deposited) * 100) : 0;

                return (
                  <BlurFade key={agent.peer_id} delay={0.03 * i} inView>
                    <div className="group relative rounded-2xl border border-white/[0.06] bg-white/[0.015] transition-all duration-300 hover:border-white/[0.12] hover:bg-white/[0.025] overflow-hidden">
                      {/* Header */}
                      <div className="flex items-center justify-between p-4 pb-3">
                        <div className="flex items-center gap-2.5">
                          <div className="w-9 h-9 rounded-lg bg-accent/10 border border-accent/20 flex items-center justify-center shrink-0">
                            <span className="text-xs font-bold text-accent">
                              {agent.label.replace("Agent ", "")}
                            </span>
                          </div>
                          <div>
                            <div className="text-[13px] font-semibold text-text-primary leading-tight">
                              {agent.label}
                            </div>
                            <div className="text-[9px] font-mono text-text-muted/40 mt-0.5">
                              {shortenId(agent.peer_id, 6)}
                              {agent.eth_address && (
                                <span className="ml-1.5 text-text-muted/30">
                                  · {agent.eth_address.slice(0, 6)}...{agent.eth_address.slice(-4)}
                                </span>
                              )}
                            </div>
                          </div>
                        </div>
                        <div className="flex items-center gap-1.5">
                          {trust > 0 && <TrustBadge score={trust} />}
                          <div className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse-soft" />
                        </div>
                      </div>

                      {/* Metrics row */}
                      <div className="grid grid-cols-4 border-y border-white/[0.04]">
                        <div className="px-3 py-2.5 text-center border-r border-white/[0.04]">
                          <div className="text-[12px] font-bold text-text-primary tabular-nums">{activeCount}<span className="text-text-muted/30 font-normal">/{agent.channels.length}</span></div>
                          <div className="text-[8px] text-text-muted/40 mt-0.5">Channels</div>
                        </div>
                        <div className="px-3 py-2.5 text-center border-r border-white/[0.04]">
                          <div className="text-[12px] font-bold text-text-primary tabular-nums">{agent.connectedPeers}</div>
                          <div className="text-[8px] text-text-muted/40 mt-0.5">Peers</div>
                        </div>
                        <div className="px-3 py-2.5 text-center border-r border-white/[0.04]">
                          <div className="text-[12px] font-bold text-accent tabular-nums">{formatWei(paidAmt)}</div>
                          <div className="text-[8px] text-text-muted/40 mt-0.5">Paid</div>
                        </div>
                        <div className="px-3 py-2.5 text-center">
                          <div className="text-[12px] font-bold text-text-primary tabular-nums">
                            {rep ? rep.payments_sent + rep.payments_received : 0}
                          </div>
                          <div className="text-[8px] text-text-muted/40 mt-0.5">Txns</div>
                        </div>
                      </div>

                      {/* Balance section */}
                      <div className="px-4 py-3">
                        {deposited > 0 ? (
                          <div>
                            <div className="flex items-center justify-between mb-1.5">
                              <span className="text-[10px] text-text-muted/50">Balance</span>
                              <span className="text-[10px] font-mono text-text-secondary tabular-nums">
                                {formatWei(remaining)} <span className="text-text-muted/30">/ {formatWei(deposited)}</span>
                              </span>
                            </div>
                            <div className="h-1.5 rounded-full bg-white/[0.04] overflow-hidden">
                              <div
                                className="h-full rounded-full bg-gradient-to-r from-accent/80 to-emerald-400/80 transition-all duration-500"
                                style={{ width: `${Math.max(3, usagePct)}%` }}
                              />
                            </div>
                            <div className="text-right mt-1">
                              <span className="text-[9px] font-mono text-emerald-400/60">{usagePct}% available</span>
                            </div>
                          </div>
                        ) : (
                          <div className="text-[10px] text-text-muted/30 text-center py-1">No deposits yet</div>
                        )}
                      </div>

                      {/* Actions */}
                      <div className="flex gap-2 px-4 pb-4">
                        <Button
                          size="sm"
                          variant="outline"
                          className="flex-1 h-8 text-[10px] font-medium border-white/[0.06] text-text-muted hover:text-text-primary hover:bg-white/[0.04] rounded-lg"
                        >
                          <Handshake className="w-3 h-3 mr-1" />
                          Negotiate
                        </Button>
                        <Button
                          size="sm"
                          className="flex-1 h-8 text-[10px] font-medium bg-accent/10 hover:bg-accent/18 text-accent border border-accent/15 rounded-lg"
                        >
                          <ExternalLink className="w-3 h-3 mr-1" />
                          Connect
                        </Button>
                      </div>
                    </div>
                  </BlurFade>
                );
              })}
            </div>
          )}
        </div>

        {/* Protocol Capabilities */}
        <BlurFade delay={0.15} inView>
          <div className="border-t border-white/[0.04] pt-10">
            <h2 className="text-sm font-semibold text-text-secondary mb-5 flex items-center gap-2">
              <Layers className="w-3.5 h-3.5 text-accent" />
              Protocol Capabilities
              <span className="text-[10px] text-text-muted/50 ml-1">
                Available on every agent
              </span>
            </h2>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {PROTOCOL_SERVICES.map((svc) => (
                <div
                  key={svc.name}
                  className="flex items-start gap-3 px-4 py-3.5 rounded-xl border border-white/[0.04] bg-white/[0.01] hover:border-white/[0.08] transition-colors"
                >
                  <div className={`w-8 h-8 rounded-lg ${svc.bg} border ${svc.border} flex items-center justify-center shrink-0 mt-0.5`}>
                    <svc.icon className={`w-3.5 h-3.5 ${svc.color}`} />
                  </div>
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-[12px] font-semibold text-text-primary">{svc.name}</span>
                      <Badge variant="outline" className={`text-[8px] font-mono ${svc.border} ${svc.color} px-1.5 py-0`}>
                        {svc.tag}
                      </Badge>
                    </div>
                    <p className="text-[11px] text-text-muted/70 leading-relaxed">{svc.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </BlurFade>
      </div>

      {/* Payment Modal */}
      {payingResource && (
        <PaymentModal
          resource={payingResource}
          apiBase={apiBase}
          onClose={() => setPayingResource(null)}
        />
      )}
    </div>
  );
}
