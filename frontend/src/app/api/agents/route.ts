import { NextResponse } from "next/server";

const BASE_API_PORT = 8080;

function agentLabel(apiPort: number): string {
  const idx = apiPort - BASE_API_PORT;
  const letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
  return `Agent ${letters[idx] || idx}`;
}

async function probeAgentPort(apiPort: number): Promise<boolean> {
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

/**
 * GET /api/agents — discover running agent processes on default port range
 */
export async function GET() {
  const SCAN_PORTS = Array.from({ length: 20 }, (_, i) => BASE_API_PORT + i);

  const checks = SCAN_PORTS.map(async (apiPort) => {
    const alive = await probeAgentPort(apiPort);
    if (!alive) return null;
    return {
      apiPort,
      label: agentLabel(apiPort),
      alive: true,
      external: true,
    };
  });

  const results = await Promise.all(checks);
  const list = results.filter((x): x is NonNullable<typeof x> => x !== null);

  return NextResponse.json({ agents: list, count: list.length });
}
