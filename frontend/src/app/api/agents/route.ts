import { NextResponse } from "next/server";

const BASE_API_PORT = 8080;
const BACKEND_HOST = process.env.BACKEND_HOST || "127.0.0.1";
// Comma-separated list of backend container hostnames (Docker mode)
const AGENT_HOSTS = (process.env.AGENT_HOSTS || "").split(",").filter(Boolean);

function agentLabel(idx: number): string {
  const letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
  return `Agent ${letters[idx] || idx}`;
}

async function probeAgent(host: string, port: number): Promise<boolean> {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 800);
    const res = await fetch(`http://${host}:${port}/health`, { signal: controller.signal });
    clearTimeout(timeout);
    if (!res.ok) return false;
    const data = await res.json();
    return data?.status === "ok";
  } catch {
    return false;
  }
}

/**
 * GET /api/agents — discover running agent processes.
 *
 * Docker mode: probes AGENT_HOSTS env var (e.g. "backend-a,backend-b,...")
 * Local mode:  scans localhost port range 8080-8099
 */
export async function GET() {
  // Docker mode: probe named container hosts
  if (AGENT_HOSTS.length > 0) {
    const checks = AGENT_HOSTS.map(async (host, i) => {
      const alive = await probeAgent(host, 8080);
      if (!alive) return null;
      return {
        apiPort: BASE_API_PORT + i,
        label: agentLabel(i),
        alive: true,
        external: true,
      };
    });

    const results = await Promise.all(checks);
    const list = results.filter((x): x is NonNullable<typeof x> => x !== null);
    return NextResponse.json({ agents: list, count: list.length });
  }

  // Local dev mode: scan port range on a single host
  const SCAN_PORTS = Array.from({ length: 20 }, (_, i) => BASE_API_PORT + i);

  const checks = SCAN_PORTS.map(async (apiPort) => {
    const alive = await probeAgent(BACKEND_HOST, apiPort);
    if (!alive) return null;
    return {
      apiPort,
      label: agentLabel(apiPort - BASE_API_PORT),
      alive: true,
      external: true,
    };
  });

  const results = await Promise.all(checks);
  const list = results.filter((x): x is NonNullable<typeof x> => x !== null);

  return NextResponse.json({ agents: list, count: list.length });
}
