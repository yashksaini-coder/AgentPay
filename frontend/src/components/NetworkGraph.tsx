"use client";

import { useEffect, useRef, useMemo, useCallback, useState } from "react";
import type { AgentState } from "@/lib/useAgent";
import { shortenId } from "@/lib/api";
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

// ── Colors ─────────────────────────────────────────────────
const NODE_COLOR = "#8b8fa3";
const NODE_COLOR_OFFLINE = "#3a3a4a";
const LINK_CHANNEL = "rgba(255,255,255,0.25)";
const LINK_P2P = "rgba(255,255,255,0.06)";
const PARTICLE_CHANNEL = "rgba(255,255,255,0.6)";
const PARTICLE_P2P = "rgba(255,255,255,0.15)";
const NODE_GLOW = "rgba(139,143,163,0.15)";

function agentLetter(i: number) { return String.fromCharCode(65 + i); }

// ── Component ─────────────────────────────────────────────
export default function NetworkGraph({
  agents,
  loadingNodes = [],
  animatingRoute,
  onInteraction,
  agentLabels,
}: {
  agents: AgentState[];
  loadingNodes?: LoadingNode[];
  animatingRoute?: AnimatingRoute | null;
  onInteraction?: (interaction: GraphInteraction) => void;
  agentLabels?: (i: number) => string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const fgRef = useRef<{ d3Force: (name: string, force?: unknown) => unknown } | null>(null);
  const selectedNodeRef = useRef<string | null>(null);
  const onInteractionRef = useRef(onInteraction);
  onInteractionRef.current = onInteraction;
  const loadingNodeSetRef = useRef(new Set<string>());
  const animatingRouteRef = useRef(animatingRoute);
  animatingRouteRef.current = animatingRoute;

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

    // Channels
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
              links.push({
                id: linkId,
                source: sa.identity.peer_id,
                target: ra.identity.peer_id,
                type: "channel",
                active: ch.state === "ACTIVE",
                label: ch.channel_id.slice(0, 8),
                channelId: ch.channel_id,
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
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const d3Force = fg.d3Force as (name: string, force?: any) => any;
    const link = d3Force("link");
    if (link) {
      link.distance((l: GraphLink) => l.type === "channel" ? 120 : 90);
      link.strength(0.5);
    }
    const charge = d3Force("charge");
    if (charge) {
      charge.strength((d: GraphNode) => d.type === "agent" ? -300 : -40);
    }
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

    // Main circle
    ctx.beginPath();
    ctx.arc(x, y, r, 0, 2 * Math.PI);
    ctx.fillStyle = node.online ? NODE_COLOR : NODE_COLOR_OFFLINE;
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
    ctx.strokeStyle = link.type === "channel" ? LINK_CHANNEL : LINK_P2P;
    ctx.lineWidth = (link.type === "channel" ? 1.5 : 0.5) / globalScale;
    ctx.stroke();

    // Channel label
    if (link.type === "channel" && link.label && globalScale > 0.5) {
      const mx = (source.x + target.x) / 2;
      const my = (source.y + target.y) / 2;
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
      {/* eslint-disable @typescript-eslint/no-explicit-any */}
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
        linkDirectionalParticles={((link: any) => link.type === "channel" ? 2 : 1) as any}
        linkDirectionalParticleWidth={((link: any) => link.type === "channel" ? 2 : 1) as any}
        linkDirectionalParticleSpeed={0.004}
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
      {/* eslint-enable @typescript-eslint/no-explicit-any */}
    </div>
  );
}
