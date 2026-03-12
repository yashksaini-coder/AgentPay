"use client";

import { useEffect, useRef, useMemo, useCallback } from "react";
import * as d3 from "d3";
import type { AgentState } from "@/lib/useAgent";
import { shortenId } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────
interface GraphNode extends d3.SimulationNodeDatum {
  id: string;
  label: string;
  type: "agent" | "peer";
  online: boolean;
  peerId?: string;
  radius: number;
}

interface GraphLink extends d3.SimulationLinkDatum<GraphNode> {
  id: string;
  type: "p2p" | "channel";
  active: boolean;
  label?: string;
  linkIndex?: number;
  linkCount?: number;
  channelId?: string;
  isNew?: boolean;
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

// ── Neutral color scheme ─────────────────────────────────
const NODE_COLOR = "#8b8fa3";           // neutral grey for all agent nodes
const NODE_COLOR_OFFLINE = "#3a3a4a";
const LINK_CHANNEL = "rgba(255,255,255,0.25)";
const LINK_P2P = "rgba(255,255,255,0.08)";
const PARTICLE_CHANNEL = "rgba(255,255,255,0.5)";
const PARTICLE_P2P = "rgba(255,255,255,0.2)";
const LABEL_CHANNEL = "rgba(255,255,255,0.5)";

function agentLetter(i: number) { return String.fromCharCode(65 + i); }

function linkArc(sx: number, sy: number, tx: number, ty: number, curvature: number): string {
  if (curvature === 0) return `M${sx},${sy}L${tx},${ty}`;
  const dx = tx - sx, dy = ty - sy;
  const dr = Math.sqrt(dx * dx + dy * dy) || 1;
  const mx = (sx + tx) / 2 + (-dy / dr) * curvature;
  const my = (sy + ty) / 2 + (dx / dr) * curvature;
  return `M${sx},${sy}Q${mx},${my},${tx},${ty}`;
}

/** Get a point along a quadratic bezier at parameter t (0-1). */
function quadPoint(sx: number, sy: number, tx: number, ty: number, curvature: number, t: number) {
  if (curvature === 0) return { x: sx + (tx - sx) * t, y: sy + (ty - sy) * t };
  const dx = tx - sx, dy = ty - sy;
  const dr = Math.sqrt(dx * dx + dy * dy) || 1;
  const cx = (sx + tx) / 2 + (-dy / dr) * curvature;
  const cy = (sy + ty) / 2 + (dx / dr) * curvature;
  const u = 1 - t;
  return {
    x: u * u * sx + 2 * u * t * cx + t * t * tx,
    y: u * u * sy + 2 * u * t * cy + t * t * ty,
  };
}

function quadMid(sx: number, sy: number, tx: number, ty: number, curvature: number) {
  return quadPoint(sx, sy, tx, ty, curvature, 0.5);
}

function curvatureForIndex(i: number, n: number): number {
  if (n <= 1) return 0;
  const spacing = 40;
  const center = (n - 1) / 2;
  return (i - center) * spacing;
}

// ── Constants ────────────────────────────────────────────
const CHANNEL_PARTICLES = 3;
const P2P_PARTICLES = 2;
const CHANNEL_SPEED = 2400;
const P2P_SPEED = 4000;

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
  const svgRef = useRef<SVGSVGElement>(null);
  const prevDataRef = useRef<string>("");
  const prevLinkIds = useRef<Set<string>>(new Set());
  const nodePositions = useRef<Map<string, { x: number; y: number }>>(new Map());
  const selectedNodeRef = useRef<string | null>(null);
  const onInteractionRef = useRef(onInteraction);
  onInteractionRef.current = onInteraction;

  // ── Loading node border animation ──
  const activeTimersRef = useRef<Map<string, d3.Timer>>(new Map());
  const FILL_DURATION = 1800;

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;

    const svgSel = d3.select(svg);
    const currentIds = new Set(loadingNodes.map((n) => n.peerId));

    for (const [peerId, timer] of activeTimersRef.current) {
      if (!currentIds.has(peerId)) {
        timer.stop();
        activeTimersRef.current.delete(peerId);
        svgSel.selectAll(`.loading-arc-${CSS.escape(peerId)}`)
          .transition().duration(300).attr("stroke-opacity", 0).remove();
      }
    }

    for (const { peerId, color } of loadingNodes) {
      if (activeTimersRef.current.has(peerId)) continue;

      let nodeGroup: d3.Selection<SVGGElement, GraphNode, null, undefined> | null = null;
      svgSel.selectAll<SVGGElement, GraphNode>("g.nodes > g").each(function (d) {
        if (d.id === peerId) {
          nodeGroup = d3.select(this) as unknown as d3.Selection<SVGGElement, GraphNode, null, undefined>;
        }
      });

      if (!nodeGroup) continue;
      const d = (nodeGroup as d3.Selection<SVGGElement, GraphNode, null, undefined>).datum();
      const group = nodeGroup as d3.Selection<SVGGElement, GraphNode, null, undefined>;

      const r = d.radius + 4;
      const circumference = 2 * Math.PI * r;

      group.append("circle")
        .attr("class", `loading-arc-${peerId}`)
        .attr("r", r).attr("fill", "none")
        .attr("stroke", color).attr("stroke-width", 6).attr("stroke-opacity", 0.08);

      const arc = group.append("circle")
        .attr("class", `loading-arc-${peerId}`)
        .attr("r", r).attr("fill", "none")
        .attr("stroke", color).attr("stroke-width", 3.5)
        .attr("stroke-opacity", 0.9).attr("stroke-linecap", "round")
        .attr("stroke-dasharray", `0 ${circumference}`)
        .attr("transform", "rotate(-90)");

      const startTime = Date.now();
      const fillTimer = d3.timer(() => {
        const progress = Math.min((Date.now() - startTime) / FILL_DURATION, 1);
        const eased = progress < 0.5
          ? 2 * progress * progress
          : 1 - Math.pow(-2 * progress + 2, 2) / 2;
        const drawn = circumference * eased;
        arc.attr("stroke-dasharray", `${drawn} ${circumference - drawn}`);
        arc.attr("stroke-opacity", 0.7 + 0.3 * eased);
        if (progress >= 1) arc.attr("stroke-dasharray", `${circumference} 0`);
      });

      activeTimersRef.current.set(peerId, fillTimer);
    }

    return () => {
      for (const [, timer] of activeTimersRef.current) timer.stop();
    };
  }, [loadingNodes]);

  // Build graph data
  const { nodes, links } = useMemo(() => {
    const n: GraphNode[] = [];
    const l: GraphLink[] = [];
    const agentPeerIds = new Set<string>();

    agents.forEach((agent, i) => {
      const pid = agent.identity?.peer_id;
      if (!pid) return;
      agentPeerIds.add(pid);
      const saved = nodePositions.current.get(pid);
      n.push({
        id: pid,
        label: agentLabels ? agentLabels(i) : `Agent ${agentLetter(i)}`,
        type: "agent",
        online: agent.online,
        peerId: pid,
        radius: 26,
        ...(saved ? { x: saved.x, y: saved.y } : {}),
      });
    });

    // Channels
    agents.forEach((agent) => {
      for (const ch of agent.channels) {
        if (ch.state === "ACTIVE" || ch.state === "OPEN") {
          const sa = agents.find((a) => a.identity?.eth_address === ch.sender);
          const ra = agents.find((a) => a.identity?.eth_address === ch.receiver);
          if (sa?.identity?.peer_id && ra?.identity?.peer_id) {
            const linkId = `ch-${ch.channel_id.slice(0, 12)}`;
            if (!l.find((x) => x.id === linkId)) {
              const isNew = !prevLinkIds.current.has(linkId);
              l.push({
                id: linkId,
                source: sa.identity.peer_id,
                target: ra.identity.peer_id,
                type: "channel",
                active: ch.state === "ACTIVE",
                label: ch.channel_id.slice(0, 8),
                channelId: ch.channel_id,
                isNew,
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
            l.push({ id: `p2p-${key}`, source: myPid, target: p.peer_id, type: "p2p", active: true });
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
      const saved = nodePositions.current.get(peerId);
      n.push({
        id: peerId, label: shortenId(peerId, 4), type: "peer", online: true,
        peerId, radius: 6,
        ...(saved ? { x: saved.x, y: saved.y } : {}),
      });
      l.push({ id: `ext-${peerId.slice(0, 8)}`, source: parentId, target: peerId, type: "p2p", active: true });
    });

    // Compute link indices
    const pairCounts = new Map<string, number>();
    for (const link of l) {
      const sId = typeof link.source === "string" ? link.source : (link.source as GraphNode).id;
      const tId = typeof link.target === "string" ? link.target : (link.target as GraphNode).id;
      const key = [sId, tId].sort().join("|");
      pairCounts.set(key, (pairCounts.get(key) || 0) + 1);
    }
    const pairIndexes = new Map<string, number>();
    for (const link of l) {
      const sId = typeof link.source === "string" ? link.source : (link.source as GraphNode).id;
      const tId = typeof link.target === "string" ? link.target : (link.target as GraphNode).id;
      const key = [sId, tId].sort().join("|");
      const idx = pairIndexes.get(key) || 0;
      link.linkIndex = idx;
      link.linkCount = pairCounts.get(key) || 1;
      pairIndexes.set(key, idx + 1);
    }

    return { nodes: n, links: l };
  }, [agents]);

  const dataKey = useMemo(
    () => JSON.stringify(nodes.map((n) => n.id + n.online).concat(links.map((l) => l.id))),
    [nodes, links]
  );

  const render = useCallback(() => {
    const svg = d3.select(svgRef.current);
    if (!svgRef.current || !containerRef.current) return;

    const { width, height } = containerRef.current.getBoundingClientRect();
    if (width === 0 || height === 0) return;

    svg.attr("width", width).attr("height", height).attr("viewBox", `0 0 ${width} ${height}`);
    svg.selectAll("*").remove();
    selectedNodeRef.current = null;

    const cx = width / 2;
    const cy = height / 2;
    const agentNodes = nodes.filter((n) => n.type === "agent");
    const spread = Math.min(width, height) * 0.3;

    // Initial positions for new nodes
    nodes.forEach((node) => {
      if (node.x !== undefined && node.y !== undefined) return;
      if (node.type === "agent") {
        const agentIdx = agentNodes.indexOf(node);
        const count = agentNodes.length;
        if (count === 1) {
          node.x = cx;
          node.y = cy;
        } else {
          const angle = (2 * Math.PI * agentIdx) / count - Math.PI / 2;
          const jitter = spread * 0.15 * (Math.random() - 0.5);
          node.x = cx + (spread + jitter) * Math.cos(angle);
          node.y = cy + (spread + jitter) * Math.sin(angle);
        }
      } else {
        node.x = cx + (Math.random() - 0.5) * spread;
        node.y = cy + (Math.random() - 0.5) * spread;
      }
    });

    // --- Defs ---
    const defs = svg.append("defs");

    // Single subtle glow for agent nodes
    const glow = defs.append("filter").attr("id", "node-glow").attr("x", "-60%").attr("y", "-60%").attr("width", "220%").attr("height", "220%");
    glow.append("feGaussianBlur").attr("stdDeviation", "6").attr("result", "blur");
    glow.append("feFlood").attr("flood-color", NODE_COLOR).attr("flood-opacity", "0.2");
    glow.append("feComposite").attr("in2", "blur").attr("operator", "in");
    const gm = glow.append("feMerge");
    gm.append("feMergeNode");
    gm.append("feMergeNode").attr("in", "SourceGraphic");

    // Particle glow filter
    const pg = defs.append("filter").attr("id", "particle-glow").attr("x", "-150%").attr("y", "-150%").attr("width", "400%").attr("height", "400%");
    pg.append("feGaussianBlur").attr("stdDeviation", "3").attr("result", "blur");
    pg.append("feFlood").attr("flood-color", "white").attr("flood-opacity", "0.5");
    pg.append("feComposite").attr("in2", "blur").attr("operator", "in");
    const pgm = pg.append("feMerge");
    pgm.append("feMergeNode");
    pgm.append("feMergeNode").attr("in", "SourceGraphic");

    // --- Zoom/Pan ---
    const zoomG = svg.append("g").attr("class", "zoom-container");

    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.3, 3])
      .on("zoom", (event) => { zoomG.attr("transform", event.transform); });

    (svg as unknown as d3.Selection<SVGSVGElement, unknown, null, undefined>).call(zoom);
    (svg as unknown as d3.Selection<SVGSVGElement, unknown, null, undefined>).call(zoom.transform, d3.zoomIdentity);

    // --- Dot grid ---
    const gridG = zoomG.append("g").attr("opacity", 0.04);
    const gridSpacing = 40;
    for (let x = 0; x < width + gridSpacing; x += gridSpacing) {
      for (let y = 0; y < height + gridSpacing; y += gridSpacing) {
        gridG.append("circle").attr("cx", x).attr("cy", y).attr("r", 0.8).attr("fill", "white");
      }
    }

    // --- Simulation ---
    const pad = 80;
    const boundaryForce = () => {
      for (const node of nodes) {
        if (node.x !== undefined && node.y !== undefined) {
          if (node.x < pad) node.vx = (node.vx || 0) + (pad - node.x) * 0.05;
          if (node.x > width - pad) node.vx = (node.vx || 0) - (node.x - (width - pad)) * 0.05;
          if (node.y < pad) node.vy = (node.vy || 0) + (pad - node.y) * 0.05;
          if (node.y > height - pad) node.vy = (node.vy || 0) - (node.y - (height - pad)) * 0.05;
        }
      }
    };

    const sim = d3.forceSimulation<GraphNode>(nodes)
      .force("link", d3.forceLink<GraphNode, GraphLink>(links).id((d) => d.id)
        .distance((l) => (l as GraphLink).type === "channel" ? 200 : 160)
        .strength(0.5))
      .force("charge", d3.forceManyBody().strength((d) => (d as GraphNode).type === "agent" ? -400 : -60))
      .force("collision", d3.forceCollide<GraphNode>().radius((d) => d.radius + 25).strength(0.8))
      .force("boundary", boundaryForce)
      .alphaDecay(0.04)
      .velocityDecay(0.45);

    const hasExisting = nodes.some((n) => nodePositions.current.has(n.id));
    sim.alpha(hasExisting ? 0.3 : 0.8).restart();

    // --- Links ---
    const linkG = zoomG.append("g").attr("class", "links");

    // Wider invisible hit area for channel links
    linkG.selectAll<SVGPathElement, GraphLink>("path.link-hit")
      .data(links.filter((l) => l.type === "channel"), (d) => d.id)
      .join("path")
      .attr("class", "link-hit")
      .attr("fill", "none")
      .attr("stroke", "transparent")
      .attr("stroke-width", 16)
      .style("cursor", "pointer")
      .on("click", (_, d) => {
        if (d.channelId && onInteractionRef.current) {
          onInteractionRef.current({ type: "channel-click", channelId: d.channelId });
        }
      });

    const linkPath = linkG.selectAll<SVGPathElement, GraphLink>("path.link-main")
      .data(links, (d) => d.id)
      .join("path")
      .attr("class", "link-main")
      .attr("fill", "none")
      .attr("stroke", (d) => d.type === "channel" ? LINK_CHANNEL : LINK_P2P)
      .attr("stroke-width", (d) => d.type === "channel" ? 2 : 1)
      .attr("stroke-opacity", (d) => {
        if (d.type !== "channel") return 1;
        return d.isNew ? 0 : 0.7;
      })
      .style("pointer-events", "none");

    // Animate new channel links
    linkPath.filter((d) => !!d.isNew && d.type === "channel").each(function(d) {
      const path = d3.select(this);
      path.transition().duration(800).ease(d3.easeCubicOut)
        .attr("stroke-opacity", 0.7).attr("stroke-width", 2);
      d.isNew = false;
    });

    // Channel dash overlay
    const dashPath = linkG.selectAll<SVGPathElement, GraphLink>("path.link-dash")
      .data(links.filter((l) => l.type === "channel"), (d) => d.id)
      .join("path")
      .attr("class", "link-dash")
      .attr("fill", "none")
      .attr("stroke", "rgba(255,255,255,0.15)")
      .attr("stroke-width", 1)
      .attr("stroke-dasharray", "4 8")
      .attr("stroke-opacity", 0.3);

    // Link hover
    const hitPaths = linkG.selectAll<SVGPathElement, GraphLink>("path.link-hit");
    hitPaths.on("mouseenter", function(_, d) {
      linkPath.filter((l) => l.id === d.id).transition().duration(120)
        .attr("stroke-width", 3.5).attr("stroke-opacity", 1).attr("stroke", "rgba(255,255,255,0.5)");
    }).on("mouseleave", function(_, d) {
      linkPath.filter((l) => l.id === d.id).transition().duration(200)
        .attr("stroke-width", 2).attr("stroke-opacity", 0.7).attr("stroke", LINK_CHANNEL);
    });

    // Link labels
    const linkLabelG = zoomG.append("g").attr("class", "link-labels");
    const linkLabels = linkLabelG.selectAll<SVGGElement, GraphLink>("g")
      .data(links.filter((l) => l.type === "channel" && !!l.label), (d) => d.id)
      .join("g")
      .style("opacity", 0);

    linkLabels.transition().delay(300).duration(600).style("opacity", 1);

    linkLabels.append("rect")
      .attr("rx", 4).attr("ry", 4)
      .attr("fill", "rgba(6,6,11,0.9)")
      .attr("stroke", "rgba(255,255,255,0.08)")
      .attr("stroke-width", 0.5);

    linkLabels.append("text")
      .text((d) => `${d.label}${d.active ? "" : " (open)"}`)
      .attr("fill", LABEL_CHANNEL)
      .attr("fill-opacity", 0.85)
      .attr("font-size", 9)
      .attr("font-family", "JetBrains Mono, monospace")
      .attr("text-anchor", "middle")
      .attr("dominant-baseline", "central");

    linkLabels.each(function() {
      const g = d3.select(this);
      const text = g.select("text").node() as SVGTextElement;
      if (text) {
        const bbox = text.getBBox();
        g.select("rect")
          .attr("x", bbox.x - 6).attr("y", bbox.y - 3)
          .attr("width", bbox.width + 12).attr("height", bbox.height + 6);
      }
    });

    // ── Continuous particle layer ──
    const particleG = zoomG.append("g").attr("class", "particles").style("pointer-events", "none");

    type ParticleInfo = {
      link: GraphLink;
      index: number;
      count: number;
      speed: number;
      radius: number;
      color: string;
      opacity: number;
    };
    const particleData: ParticleInfo[] = [];
    for (const link of links) {
      if (link.type === "channel") {
        for (let p = 0; p < CHANNEL_PARTICLES; p++) {
          particleData.push({
            link, index: p, count: CHANNEL_PARTICLES,
            speed: CHANNEL_SPEED + (p * 200), radius: 2,
            color: PARTICLE_CHANNEL, opacity: 0.6,
          });
        }
      } else if (link.type === "p2p") {
        for (let p = 0; p < P2P_PARTICLES; p++) {
          particleData.push({
            link, index: p, count: P2P_PARTICLES,
            speed: P2P_SPEED + (p * 600), radius: 1.2,
            color: PARTICLE_P2P, opacity: 0.25,
          });
        }
      }
    }

    const particleSel = particleG.selectAll<SVGCircleElement, ParticleInfo>("circle")
      .data(particleData)
      .join("circle")
      .attr("r", (d) => d.radius)
      .attr("fill", (d) => d.color)
      .attr("opacity", 0)
      .attr("filter", (d) => d.link.type === "channel" ? "url(#particle-glow)" : null);

    // --- Nodes ---
    const nodeG = zoomG.append("g").attr("class", "nodes");
    const nodeSel = nodeG.selectAll<SVGGElement, GraphNode>("g")
      .data(nodes, (d) => d.id)
      .join("g")
      .attr("cursor", "grab");

    // --- Drag ---
    const dragBehavior = d3.drag<SVGGElement, GraphNode>()
      .on("start", (event, d) => {
        if (!event.active) sim.alphaTarget(0.1).restart();
        d.fx = d.x;
        d.fy = d.y;
      })
      .on("drag", (event, d) => {
        d.fx = event.x;
        d.fy = event.y;
      })
      .on("end", (event, d) => {
        if (!event.active) sim.alphaTarget(0);
        d.fx = null;
        d.fy = null;
      });
    nodeSel.call(dragBehavior);

    // --- Agent visuals ---
    const agentSel = nodeSel.filter((d) => d.type === "agent");

    // Selection ring (hidden by default)
    agentSel.append("circle")
      .attr("r", 34).attr("fill", "none")
      .attr("stroke", "rgba(255,255,255,0.6)").attr("stroke-width", 2.5)
      .attr("stroke-dasharray", "6 4")
      .attr("opacity", 0).attr("class", "select-ring");

    // Breathing ring
    agentSel.filter((d) => d.online).append("circle")
      .attr("r", 34).attr("fill", "none")
      .attr("stroke", "rgba(255,255,255,0.3)").attr("stroke-width", 1)
      .attr("opacity", 0.1).attr("class", "pulse-ring");

    // Main circle — neutral color for all nodes
    agentSel.append("circle")
      .attr("r", (d) => d.radius)
      .attr("fill", (d) => d.online ? NODE_COLOR : NODE_COLOR_OFFLINE)
      .attr("fill-opacity", (d) => d.online ? 0.85 : 0.3)
      .attr("stroke", "rgba(255,255,255,0.2)")
      .attr("stroke-width", 1.5)
      .attr("stroke-opacity", (d) => d.online ? 0.4 : 0.15)
      .attr("filter", (d) => d.online ? "url(#node-glow)" : null)
      .attr("class", "node-circle");

    // Entry animation for new nodes
    const isNew = (d: GraphNode) => !nodePositions.current.has(d.id);
    agentSel.filter(isNew)
      .attr("transform", (d) => `translate(${d.x},${d.y}) scale(0)`)
      .transition().duration(500).ease(d3.easeBackOut.overshoot(1.2))
      .attr("transform", (d) => `translate(${d.x},${d.y}) scale(1)`);

    // --- Click-to-connect ---
    agentSel.on("click", function(event, d) {
      event.stopPropagation();
      if (!d.online || d.type !== "agent") return;

      const prevSelected = selectedNodeRef.current;

      if (prevSelected && prevSelected !== d.id) {
        if (onInteractionRef.current) {
          onInteractionRef.current({
            type: "node-pair",
            sourcePeerId: prevSelected,
            targetPeerId: d.id,
          });
        }
        selectedNodeRef.current = null;
        nodeG.selectAll(".select-ring").transition().duration(200).attr("opacity", 0);
      } else if (prevSelected === d.id) {
        selectedNodeRef.current = null;
        d3.select(this).select(".select-ring").transition().duration(200).attr("opacity", 0);
      } else {
        selectedNodeRef.current = d.id;
        nodeG.selectAll(".select-ring").transition().duration(200).attr("opacity", 0);
        d3.select(this).select(".select-ring").transition().duration(200).attr("opacity", 0.7);
      }
    });

    // Click on background to deselect
    svg.on("click", () => {
      selectedNodeRef.current = null;
      nodeG.selectAll(".select-ring").transition().duration(200).attr("opacity", 0);
    });

    // Hover effects
    agentSel
      .on("mouseenter", function(_, d) {
        if (!d.online) return;
        d3.select(this).select(".node-circle")
          .transition().duration(120)
          .attr("r", d.radius + 4).attr("fill-opacity", 1).attr("stroke-opacity", 0.7);
        d3.select(this).select(".pulse-ring")
          .transition().duration(120).attr("r", 40).attr("opacity", 0.2);

        linkPath.transition().duration(120)
          .attr("stroke-opacity", (l) => {
            const s = (l.source as GraphNode).id, t = (l.target as GraphNode).id;
            const connected = s === d.id || t === d.id;
            if (l.type === "channel") return connected ? 1 : 0.15;
            return connected ? 0.2 : 0.05;
          })
          .attr("stroke-width", (l) => {
            const s = (l.source as GraphNode).id, t = (l.target as GraphNode).id;
            if (l.type === "channel" && (s === d.id || t === d.id)) return 3;
            return l.type === "channel" ? 2 : 1;
          });

        nodeSel.filter((n) => n.id !== d.id).select(".node-circle")
          .transition().duration(120).attr("fill-opacity", 0.35);
      })
      .on("mouseleave", function(_, d) {
        d3.select(this).select(".node-circle")
          .transition().duration(250)
          .attr("r", d.radius).attr("fill-opacity", 0.85).attr("stroke-opacity", 0.4);
        d3.select(this).select(".pulse-ring")
          .transition().duration(250).attr("r", 34).attr("opacity", 0.1);

        linkPath.transition().duration(250)
          .attr("stroke-opacity", (l) => l.type === "channel" ? 0.7 : 0.08)
          .attr("stroke-width", (l) => l.type === "channel" ? 2 : 1);

        nodeSel.select(".node-circle")
          .transition().duration(250).attr("fill-opacity", (n) => (n as GraphNode).online ? 0.85 : 0.3);
      });

    // Letter inside circle
    agentSel.append("text")
      .text((d) => {
        const stripped = d.label.replace(/^Agent\s*/i, "");
        return stripped.length <= 3 ? stripped : stripped.slice(0, 2);
      })
      .attr("fill", "white").attr("font-size", 15).attr("font-weight", 700)
      .attr("font-family", "Inter, system-ui")
      .attr("text-anchor", "middle").attr("dominant-baseline", "central")
      .style("pointer-events", "none");
    agentSel.append("title").text((d) => d.label);

    // --- Peer nodes ---
    const peerSel = nodeSel.filter((d) => d.type === "peer");
    peerSel.append("circle")
      .attr("r", (d) => d.radius)
      .attr("fill", "#5a5a6a").attr("fill-opacity", 0.5)
      .attr("stroke", "#5a5a6a").attr("stroke-width", 1).attr("stroke-opacity", 0.3)
      .attr("class", "node-circle");
    peerSel.append("title").text((d) => d.label);

    // ── Continuous animation timer ──
    const animStartTime = Date.now();

    const animate = d3.timer((elapsed) => {
      // Breathing
      const scale = 1 + 0.06 * Math.sin(elapsed / 1500);
      const breatheOp = 0.06 + 0.03 * Math.sin(elapsed / 1500);
      agentSel.selectAll(".pulse-ring")
        .attr("r", 34 * scale).attr("opacity", breatheOp);

      // Channel link subtle pulse
      const glowPulse = 0.55 + 0.15 * Math.sin(elapsed / 2500);
      linkPath.filter((l) => l.type === "channel")
        .attr("stroke-opacity", glowPulse);

      // Particle flow along links
      const now = Date.now();
      particleSel.each(function(d) {
        const s = d.link.source as GraphNode;
        const t = d.link.target as GraphNode;
        if (s.x == null || s.y == null || t.x == null || t.y == null) return;

        const curv = curvatureForIndex(d.link.linkIndex || 0, d.link.linkCount || 1);
        const offset = d.index / d.count;
        const param = ((now - animStartTime) / d.speed + offset) % 1;
        const pos = quadPoint(s.x, s.y, t.x, t.y, curv, param);

        const fadeZone = 0.08;
        let op = d.opacity;
        if (param < fadeZone) op *= param / fadeZone;
        else if (param > 1 - fadeZone) op *= (1 - param) / fadeZone;

        d3.select(this)
          .attr("cx", pos.x)
          .attr("cy", pos.y)
          .attr("opacity", op);
      });
    });

    // --- Tick ---
    let dashOffset = 0;
    sim.on("tick", () => {
      const hitPathsSel = linkG.selectAll<SVGPathElement, GraphLink>("path.link-hit");
      hitPathsSel.attr("d", (d) => {
        const s = d.source as GraphNode, t = d.target as GraphNode;
        return linkArc(s.x!, s.y!, t.x!, t.y!, curvatureForIndex(d.linkIndex || 0, d.linkCount || 1));
      });

      linkPath.attr("d", (d) => {
        const s = d.source as GraphNode, t = d.target as GraphNode;
        return linkArc(s.x!, s.y!, t.x!, t.y!, curvatureForIndex(d.linkIndex || 0, d.linkCount || 1));
      });

      dashPath.attr("d", (d) => {
        const s = d.source as GraphNode, t = d.target as GraphNode;
        return linkArc(s.x!, s.y!, t.x!, t.y!, curvatureForIndex(d.linkIndex || 0, d.linkCount || 1));
      });

      dashOffset -= 0.5;
      dashPath.attr("stroke-dashoffset", dashOffset);

      linkLabels.attr("transform", (d) => {
        const s = d.source as GraphNode, t = d.target as GraphNode;
        const m = quadMid(s.x!, s.y!, t.x!, t.y!, curvatureForIndex(d.linkIndex || 0, d.linkCount || 1));
        return `translate(${m.x},${m.y})`;
      });

      nodeSel.attr("transform", (d) => `translate(${d.x},${d.y})`);

      for (const node of nodes) {
        if (node.x !== undefined && node.y !== undefined) {
          nodePositions.current.set(node.id, { x: node.x, y: node.y });
        }
      }
    });

    prevLinkIds.current = new Set(links.map((l) => l.id));

    return () => {
      sim.stop();
      animate.stop();
    };
  }, [nodes, links]);

  const renderRef = useRef(render);
  renderRef.current = render;

  useEffect(() => {
    if (dataKey === prevDataRef.current) return;
    prevDataRef.current = dataKey;
    const cleanup = renderRef.current();
    return cleanup;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataKey]);

  useEffect(() => {
    const observer = new ResizeObserver(() => { prevDataRef.current = ""; });
    if (containerRef.current) observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  return (
    <div ref={containerRef} className="relative w-full h-full overflow-hidden">
      <svg ref={svgRef} className="w-full h-full" />
    </div>
  );
}
