import { NextResponse } from "next/server";

const BASE_API_PORT = 8080;
const API_URL = process.env.NEXT_PUBLIC_API_URL || "";

function isRemote(): boolean {
  return !!API_URL && !API_URL.includes("127.0.0.1") && !API_URL.includes("localhost") && !API_URL.startsWith("/");
}

function agentLabel(idx: number): string {
  const letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
  return `Agent ${letters[idx] || idx}`;
}

async function probePort(apiPort: number): Promise<boolean> {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 800);
    const res = await fetch(`http://127.0.0.1:${apiPort}/health`, { signal: controller.signal });
    clearTimeout(timeout);
    if (!res.ok) return false;
    const data = await res.json();
    return data?.status === "ok";
  } catch {
    return false;
  }
}

interface DiscoveredAgent {
  peer_id: string;
  eth_address: string;
  capabilities: { service_type: string; price_per_call: number; description: string; role?: string }[];
  addrs: string[];
}

/**
 * GET /api/agents
 *
 * Local mode:  scan localhost ports 8080-8099 for healthy agents.
 * Remote mode: query the backend's /discovery/agents + /identity endpoints
 *              to get all agents known to the network, marking the live node.
 */
export async function GET() {
  if (isRemote()) {
    try {
      // Verify backend is healthy + fetch identity and discovery in parallel
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 3000);
      const [healthRes, discRes, idRes] = await Promise.all([
        fetch(`${API_URL}/health`, { signal: controller.signal }),
        fetch(`${API_URL}/discovery/agents`, { signal: controller.signal }),
        fetch(`${API_URL}/identity`, { signal: controller.signal }),
      ]);
      clearTimeout(timeout);

      if (!healthRes.ok) {
        return NextResponse.json({ agents: [], count: 0, backend: "offline" });
      }
      const health = await healthRes.json();
      if (health?.status !== "ok") {
        return NextResponse.json({ agents: [], count: 0, backend: "unhealthy" });
      }

      // Get the real node's peer_id so we can flag it as "live"
      const identity = idRes.ok ? await idRes.json() : null;
      const livePeerId = identity?.peer_id || "";

      if (discRes.ok) {
        const disc = await discRes.json();
        const discoveredAgents: DiscoveredAgent[] = disc.agents || [];

        if (discoveredAgents.length > 0) {
          const agents = discoveredAgents.map((agent, idx) => ({
            apiPort: 0,
            label: agentLabel(idx),
            alive: true,
            external: true,
            url: API_URL,
            // Discovery identity data
            peer_id: agent.peer_id,
            eth_address: agent.eth_address,
            capabilities: agent.capabilities,
            addrs: agent.addrs,
            // Flag: this agent has a live backend API (vs. discovered-only)
            live: agent.peer_id === livePeerId,
          }));
          return NextResponse.json({
            agents,
            count: agents.length,
            backend: "online",
          });
        }
      }

      // Fallback: return single agent from health check
      return NextResponse.json({
        agents: [{
          apiPort: 0, label: "Agent A", alive: true, external: true, url: API_URL,
          peer_id: livePeerId, eth_address: identity?.eth_address || "",
          capabilities: [], addrs: identity?.addrs || [], live: true,
        }],
        count: 1,
        backend: "online",
      });
    } catch {
      return NextResponse.json({ agents: [], count: 0, backend: "offline" });
    }
  }

  // Local: scan ports
  const SCAN_PORTS = Array.from({ length: 20 }, (_, i) => BASE_API_PORT + i);
  const checks = SCAN_PORTS.map(async (apiPort) => {
    const alive = await probePort(apiPort);
    if (!alive) return null;
    return {
      apiPort,
      label: agentLabel(apiPort - BASE_API_PORT),
      alive: true,
      external: true,
      live: true,
    };
  });

  const results = await Promise.all(checks);
  const list = results.filter((x): x is NonNullable<typeof x> => x !== null);
  const backend = list.length > 0 ? "online" : "offline";

  return NextResponse.json({ agents: list, count: list.length, backend });
}
