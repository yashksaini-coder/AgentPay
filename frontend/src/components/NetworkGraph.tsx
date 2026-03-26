"use client";

import { useEffect, useRef, useMemo, useCallback, useState } from "react";
import type { AgentState } from "@/lib/useAgent";
import { shortenId, formatWei } from "@/lib/api";
import dynamic from "next/dynamic";

// Lazy-load react-force-graph-2d to avoid SSR issues (Canvas/window)
const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false });

// ── Types ─────────────────────────────────────────────────
interface GraphNode {
  id: string;
  label: string;
  type: "agent" | "peer";
  online: boolean;
  peerId?: string;
  radius: number;
  x?: number;
  y?: number;
  fx?: number;
  fy?: number;
}

interface GraphLink {
  id: string;
  source: string;
  target: string;
  type: "p2p" | "channel";
  active: boolean;
  label?: string;
  channelId?: string;
  utilization?: number; // 0.0 (fresh) to 1.0 (fully spent)
}

export interface LoadingNode {
  peerId: string;
  color: string;
}

export interface GraphInteraction {
  type: "node-pair" | "channel-click";
  sourcePeerId?: string;
  targetPeerId?: string;
  channelId?: string;
}

export interface AnimatingRoute {
  hops: string[];
  color: string;
  type: "payment" | "channel";
}

export interface PaymentEvent {
  channelId: string;
  amount: number;
  timestamp: number;
  senderPeerId?: string;
  receiverPeerId?: string;
}

// ── Colors ─────────────────────────────────────────────────
const NODE_COLOR = "#8b8fa3";
const NODE_COLOR_OFFLINE = "#3a3a4a";
const LINK_P2P = "rgba(255,255,255,0.06)";
const PARTICLE_CHANNEL = "rgba(255,255,255,0.6)";
const PARTICLE_P2P = "rgba(255,255,255,0.15)";
const NODE_GLOW = "rgba(139,143,163,0.15)";
const PULSE_GREEN = "#34d399";
const PULSE_AMBER = "#fbbf24";
const PULSE_RED = "#f87171";
const TRANSFER_FLASH = "#fbbf24";

function agentLetter(i: number) { return String.fromCharCode(65 + i); }

// ── Component ─────────────────────────────────────────────
export default function NetworkGraph({
  agents,
  loadingNodes = [],
  animatingRoute,
  onInteraction,
  agentLabels,
  trustScores = {},
  paymentEvents = [],
}: {
  agents: AgentState[];
  loadingNodes?: LoadingNode[];
  animatingRoute?: AnimatingRoute | null;
  onInteraction?: (interaction: GraphInteraction) => void;
  agentLabels?: (i: number) => string;
  trustScores?: Record<string, number>;
  paymentEvents?: PaymentEvent[];
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const fgRef = useRef<any>(null);
  const selectedNodeRef = useRef<string | null>(null);
  const onInteractionRef = useRef(onInteraction);
  onInteractionRef.current = onInteraction; // eslint-disable-line react-hooks/refs
  const loadingNodeSetRef = useRef(new Set<string>());
  const animatingRouteRef = useRef(animatingRoute);
  animatingRouteRef.current = animatingRoute; // eslint-disable-line react-hooks/refs
  const trustScoresRef = useRef(trustScores);
  trustScoresRef.current = trustScores; // eslint-disable-line react-hooks/refs

  // netviz-inspired: pulse rings for state transitions
  const pulseRingsRef = useRef<Map<string, { startTime: number; color: string }>>(new Map());
  // netviz-inspired: recent transfer amounts for flash labels
  const recentTransfersRef = useRef<Map<string, { amount: number; timestamp: number }>>(new Map());
  // Track processed payment event timestamps to avoid duplicates
  const processedEventsRef = useRef(new Set<string>());

  // Track container dimensions for responsive sizing
  const [dimensions, setDimensions] = useState<{ width: number; height: number }>({ width: 800, height: 600 });
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const update = () => {
      const { width, height } = el.getBoundingClientRect();
      if (width > 0 && height > 0) setDimensions({ width, height });
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Track loading nodes
  useEffect(() => {
    loadingNodeSetRef.current = new Set(loadingNodes.map((n) => n.peerId));
  }, [loadingNodes]);

  // netviz-inspired: emit particle bursts + pulse rings on payment events
  useEffect(() => {
    for (const evt of paymentEvents) {
      const key = `${evt.channelId}-${evt.timestamp}`;
      if (processedEventsRef.current.has(key)) continue;
      processedEventsRef.current.add(key);

      // Flash transfer amount on the channel link
      recentTransfersRef.current.set(evt.channelId, {
        amount: evt.amount,
        timestamp: Date.now(),
      });

      // Pulse rings on sender and receiver nodes
      if (evt.senderPeerId) {
        pulseRingsRef.current.set(evt.senderPeerId, {
          startTime: Date.now(),
          color: PULSE_AMBER,
        });
      }
      if (evt.receiverPeerId) {
        pulseRingsRef.current.set(evt.receiverPeerId, {
          startTime: Date.now(),
          color: PULSE_GREEN,
        });
      }

      // Emit particle burst on the matching link
      const fg = fgRef.current;
      if (fg && typeof fg.emitParticle === "function") {
        const graphLinks = fg.graphData?.()?.links ?? [];
        const matchingLink = graphLinks.find(
          (l: any) => l.channelId === evt.channelId
        );
        if (matchingLink) {
          for (let i = 0; i < 4; i++) {
            setTimeout(() => fg.emitParticle(matchingLink), i * 60);
          }
        }
      }
    }

    // Cleanup old processed events (keep last 200)
    if (processedEventsRef.current.size > 200) {
      const arr = [...processedEventsRef.current];
      processedEventsRef.current = new Set(arr.slice(-100));
    }
  }, [paymentEvents]);

  // Build graph data
  const graphData = useMemo(() => {
    const nodes: GraphNode[] = [];
    const links: GraphLink[] = [];
    const agentPeerIds = new Set<string>();

    agents.forEach((agent, i) => {
      const pid = agent.identity?.peer_id;
      if (!pid) return;
      agentPeerIds.add(pid);
      nodes.push({
        id: pid,
        label: agentLabels ? agentLabels(i) : `Agent ${agentLetter(i)}`,
        type: "agent",
        online: agent.online,
        peerId: pid,
        radius: 22,
      });
    });

    // Channels — with utilization for health gradient
    const seenLinks = new Set<string>();
    agents.forEach((agent) => {
      for (const ch of agent.channels) {
        if (ch.state === "ACTIVE" || ch.state === "OPEN") {
          const sa = agents.find((a) => a.identity?.eth_address === ch.sender);
          const ra = agents.find((a) => a.identity?.eth_address === ch.receiver);
          if (sa?.identity?.peer_id && ra?.identity?.peer_id) {
            const linkId = `ch-${ch.channel_id.slice(0, 12)}`;
            if (!seenLinks.has(linkId)) {
              seenLinks.add(linkId);
              const utilization = ch.total_deposit > 0
                ? ch.total_paid / ch.total_deposit
                : 0;
              links.push({
                id: linkId,
                source: sa.identity.peer_id,
                target: ra.identity.peer_id,
                type: "channel",
                active: ch.state === "ACTIVE",
                label: ch.channel_id.slice(0, 8),
                channelId: ch.channel_id,
                utilization,
              });
            }
          }
        }
      }
    });

    // P2P connections
    const connPairs = new Set<string>();
    agents.forEach((agent) => {
      const myPid = agent.identity?.peer_id;
      if (!myPid) return;
      for (const p of agent.peers) {
        if (agentPeerIds.has(p.peer_id)) {
          const key = [myPid, p.peer_id].sort().join(":");
          if (!connPairs.has(key)) {
            connPairs.add(key);
            links.push({ id: `p2p-${key}`, source: myPid, target: p.peer_id, type: "p2p", active: true });
          }
        }
      }
    });

    // External peers
    const ext = new Map<string, string>();
    agents.forEach((agent) => {
      const myPid = agent.identity?.peer_id;
      if (!myPid) return;
      for (const p of agent.peers) {
        if (!agentPeerIds.has(p.peer_id) && !ext.has(p.peer_id)) ext.set(p.peer_id, myPid);
      }
    });
    ext.forEach((parentId, peerId) => {
      nodes.push({
        id: peerId, label: shortenId(peerId, 4), type: "peer", online: true,
        peerId, radius: 4,
      });
      links.push({ id: `ext-${peerId.slice(0, 8)}`, source: parentId, target: peerId, type: "p2p", active: true });
    });

    return { nodes, links };
  }, [agents, agentLabels]);

  // Tune forces when graph data changes
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;
    const d3Force = fg.d3Force as (name: string, force?: any) => any;
    const link = d3Force("link");
    if (link) {
      link.distance((l: GraphLink) => l.type === "channel" ? 90 : 70);
      link.strength(0.5);
    }
    const charge = d3Force("charge");
    if (charge) {
      charge.strength((d: GraphNode) => d.type === "agent" ? -200 : -30);
    }
  }, [graphData]);

  // Zoom out once on initial load — never auto-zoom after that
  const hasZoomedRef = useRef(false);
  useEffect(() => {
    if (hasZoomedRef.current) return;
    const fg = fgRef.current;
    if (!fg || graphData.nodes.length === 0) return;
    const fgAny = fg as any;
    const timer = setTimeout(() => {
      if (typeof fgAny.zoom === "function") {
        fgAny.zoom(0.5, 400);
      }
      hasZoomedRef.current = true;
    }, 800);
    return () => clearTimeout(timer);
  }, [graphData]);

  // ── Custom Canvas node renderer ───────────────────────
  const paintNode = useCallback((node: GraphNode, ctx: CanvasRenderingContext2D, globalScale: number) => {
    const r = node.radius;
    const x = node.x ?? 0;
    const y = node.y ?? 0;
    const isSelected = selectedNodeRef.current === node.id;
    const isLoading = loadingNodeSetRef.current.has(node.id);

    if (node.type === "peer") {
      ctx.beginPath();
      ctx.arc(x, y, r, 0, 2 * Math.PI);
      ctx.fillStyle = "#5a5a6a";
      ctx.globalAlpha = 0.5;
      ctx.fill();
      ctx.globalAlpha = 1;
      return;
    }

    // Glow
    if (node.online) {
      ctx.beginPath();
      ctx.arc(x, y, r + 8, 0, 2 * Math.PI);
      ctx.fillStyle = NODE_GLOW;
      ctx.fill();
    }

    // Selection ring
    if (isSelected) {
      ctx.beginPath();
      ctx.arc(x, y, r + 6, 0, 2 * Math.PI);
      ctx.strokeStyle = "rgba(255,255,255,0.6)";
      ctx.lineWidth = 2 / globalScale;
      ctx.setLineDash([4 / globalScale, 3 / globalScale]);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // Loading ring
    if (isLoading) {
      const loadingNode = loadingNodes.find((n) => n.peerId === node.id);
      if (loadingNode) {
        ctx.beginPath();
        ctx.arc(x, y, r + 5, -Math.PI / 2, -Math.PI / 2 + (Date.now() % 1800) / 1800 * 2 * Math.PI);
        ctx.strokeStyle = loadingNode.color;
        ctx.lineWidth = 3 / globalScale;
        ctx.stroke();
      }
    }

    // Route highlight
    const route = animatingRouteRef.current;
    if (route && route.hops.includes(node.id)) {
      ctx.beginPath();
      ctx.arc(x, y, r + 4, 0, 2 * Math.PI);
      ctx.strokeStyle = route.color;
      ctx.lineWidth = 2.5 / globalScale;
      ctx.stroke();
    }

    // netviz-inspired: expanding pulse ring on state transitions
    const pulse = pulseRingsRef.current.get(node.id);
    if (pulse) {
      const elapsed = Date.now() - pulse.startTime;
      const duration = 1500;
      if (elapsed > duration) {
        pulseRingsRef.current.delete(node.id);
      } else {
        const progress = elapsed / duration;
        const ringRadius = r + (25 * progress);
        const alpha = (1 - progress) * 0.6;
        ctx.beginPath();
        ctx.arc(x, y, ringRadius, 0, 2 * Math.PI);
        ctx.strokeStyle = pulse.color;
        ctx.globalAlpha = alpha;
        ctx.lineWidth = (2.5 - progress * 1.5) / globalScale;
        ctx.stroke();
        ctx.globalAlpha = 1;
      }
    }

    // Main circle
    ctx.beginPath();
    ctx.arc(x, y, r, 0, 2 * Math.PI);
    // Color by trust score if available (green=high, amber=mid, red=low)
    const ts = node.peerId ? trustScoresRef.current[node.peerId] : undefined;
    const baseColor = !node.online ? NODE_COLOR_OFFLINE
      : ts !== undefined ? (ts >= 0.7 ? PULSE_GREEN : ts >= 0.4 ? PULSE_AMBER : PULSE_RED)
      : NODE_COLOR;
    ctx.fillStyle = baseColor;
    ctx.globalAlpha = node.online ? 0.85 : 0.3;
    ctx.fill();
    ctx.globalAlpha = 1;

    // Border
    ctx.strokeStyle = "rgba(255,255,255,0.2)";
    ctx.lineWidth = 1.5 / globalScale;
    ctx.stroke();

    // Label text
    const stripped = node.label.replace(/^Agent\s*/i, "");
    const labelText = stripped.length <= 3 ? stripped : stripped.slice(0, 2);
    const fontSize = Math.min(14, 14 / globalScale * Math.min(globalScale, 1.5));
    ctx.font = `bold ${fontSize}px Inter, system-ui, sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillStyle = "white";
    ctx.fillText(labelText, x, y);
  }, [loadingNodes]);

  // ── Custom link renderer ──────────────────────────────
  const paintLink = useCallback((link: GraphLink, ctx: CanvasRenderingContext2D, globalScale: number) => {
    const source = link.source as unknown as GraphNode;
    const target = link.target as unknown as GraphNode;
    if (!source.x || !source.y || !target.x || !target.y) return;

    ctx.beginPath();
    ctx.moveTo(source.x, source.y);
    ctx.lineTo(target.x, target.y);

    // netviz-inspired: channel health gradient (green → amber → red by utilization)
    if (link.type === "channel" && link.utilization !== undefined && link.utilization > 0) {
      const u = link.utilization;
      const gradient = ctx.createLinearGradient(source.x, source.y, target.x, target.y);
      if (u < 0.5) {
        gradient.addColorStop(0, `rgba(52,211,153,${0.25 + u * 0.3})`);
        gradient.addColorStop(1, `rgba(251,191,36,${0.15 + u * 0.35})`);
      } else {
        gradient.addColorStop(0, `rgba(251,191,36,${0.35 + (u - 0.5) * 0.2})`);
        gradient.addColorStop(1, `rgba(248,113,113,${0.25 + (u - 0.5) * 0.5})`);
      }
      ctx.strokeStyle = gradient;
      ctx.lineWidth = (1.5 + u * 1.5) / globalScale;
    } else {
      ctx.strokeStyle = link.type === "channel" ? "rgba(255,255,255,0.25)" : LINK_P2P;
      ctx.lineWidth = (link.type === "channel" ? 1.5 : 0.5) / globalScale;
    }
    ctx.stroke();

    // Channel label + transfer flash
    if (link.type === "channel" && globalScale > 0.5) {
      const mx = (source.x + target.x) / 2;
      const my = (source.y + target.y) / 2;

      // netviz-inspired: flash transfer amount above channel label
      if (link.channelId) {
        const transfer = recentTransfersRef.current.get(link.channelId);
        if (transfer) {
          const elapsed = Date.now() - transfer.timestamp;
          const fadeDuration = 2500;
          if (elapsed > fadeDuration) {
            recentTransfersRef.current.delete(link.channelId);
          } else {
            const alpha = 1 - (elapsed / fadeDuration);
            const offsetY = -14 / globalScale;
            const flashSize = Math.max(8, 11 / globalScale);
            ctx.font = `bold ${flashSize}px JetBrains Mono, monospace`;
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            ctx.globalAlpha = alpha * 0.95;
            ctx.fillStyle = TRANSFER_FLASH;
            ctx.fillText(formatWei(transfer.amount), mx, my + offsetY);
            ctx.globalAlpha = 1;
          }
        }
      }

      // Static channel label
      if (link.label) {
        const fontSize = Math.max(7, 9 / globalScale);
        ctx.font = `${fontSize}px JetBrains Mono, monospace`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";

        // Background
        const metrics = ctx.measureText(link.label);
        const pad = 3 / globalScale;
        ctx.fillStyle = "rgba(6,6,11,0.85)";
        ctx.fillRect(mx - metrics.width / 2 - pad, my - fontSize / 2 - pad, metrics.width + pad * 2, fontSize + pad * 2);

        ctx.fillStyle = "rgba(255,255,255,0.5)";
        ctx.fillText(link.label, mx, my);
      }
    }
  }, []);

  // ── Click handlers ────────────────────────────────────
  const handleNodeClick = useCallback((node: GraphNode) => {
    if (!node.online || node.type !== "agent") return;

    const prevSelected = selectedNodeRef.current;
    if (prevSelected && prevSelected !== node.id) {
      if (onInteractionRef.current) {
        onInteractionRef.current({
          type: "node-pair",
          sourcePeerId: prevSelected,
          targetPeerId: node.id,
        });
      }
      selectedNodeRef.current = null;
    } else if (prevSelected === node.id) {
      selectedNodeRef.current = null;
    } else {
      selectedNodeRef.current = node.id;
    }
  }, []);

  const handleLinkClick = useCallback((link: GraphLink) => {
    if (link.channelId && onInteractionRef.current) {
      onInteractionRef.current({ type: "channel-click", channelId: link.channelId });
    }
  }, []);

  const handleBackgroundClick = useCallback(() => {
    selectedNodeRef.current = null;
  }, []);

  return (
    <div ref={containerRef} className="relative w-full h-full overflow-hidden">
      <ForceGraph2D
        ref={fgRef as any}
        graphData={graphData as any}
        nodeId="id"
        nodeRelSize={1}
        nodeCanvasObject={paintNode as any}
        nodePointerAreaPaint={((node: any, color: string, ctx: CanvasRenderingContext2D) => {
          ctx.beginPath();
          ctx.arc(node.x ?? 0, node.y ?? 0, (node.radius ?? 22) + 4, 0, 2 * Math.PI);
          ctx.fillStyle = color;
          ctx.fill();
        }) as any}
        linkCanvasObject={paintLink as any}
        linkDirectionalParticles={((link: any) => link.type === "channel" ? 1 : 0) as any}
        linkDirectionalParticleWidth={((link: any) => link.type === "channel" ? 2.5 : 1) as any}
        linkDirectionalParticleSpeed={0.005}
        linkDirectionalParticleColor={((link: any) => link.type === "channel" ? PARTICLE_CHANNEL : PARTICLE_P2P) as any}
        onNodeClick={((node: any) => handleNodeClick(node)) as any}
        onLinkClick={((link: any) => handleLinkClick(link)) as any}
        onBackgroundClick={handleBackgroundClick}
        enableNodeDrag={true}
        cooldownTicks={100}
        d3AlphaDecay={0.08}
        d3VelocityDecay={0.4}
        backgroundColor="rgba(0,0,0,0)"
        width={dimensions.width}
        height={dimensions.height}
      />
    </div>
  );
}
