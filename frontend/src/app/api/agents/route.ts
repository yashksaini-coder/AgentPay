import { NextResponse } from "next/server";
import { spawn, type ChildProcess } from "child_process";
import { createConnection } from "net";
import path from "path";

/**
 * In-memory registry of agent processes.
 * Module-level so it persists across API requests in dev server.
 */
interface AgentProcess {
  pid: number;
  port: number;        // TCP p2p port
  wsPort: number;      // WebSocket port
  apiPort: number;     // REST API port
  identityPath: string;
  process: ChildProcess;
  startedAt: number;
  label: string;
}

const agents = new Map<number, AgentProcess>();

// Port allocation
const BASE_P2P_PORT = 9000;
const BASE_WS_PORT = 9001;
const BASE_API_PORT = 8080;

// Hard cap on managed agents to prevent resource exhaustion
const MAX_AGENTS = 20;

// Project root (two levels up from frontend/src/app/api/agents/)
const PROJECT_ROOT = path.resolve(process.cwd(), "..");

function isPortInUse(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const socket = createConnection({ port, host: "127.0.0.1" });
    socket.setTimeout(500);
    socket.on("connect", () => {
      socket.destroy();
      resolve(true);
    });
    socket.on("timeout", () => {
      socket.destroy();
      resolve(false);
    });
    socket.on("error", () => {
      resolve(false);
    });
  });
}

async function nextAvailablePorts(): Promise<{ port: number; wsPort: number; apiPort: number }> {
  const usedApiPorts = new Set(Array.from(agents.values()).map((a) => a.apiPort));
  let index = 0;
  while (index < 100) {
    const apiPort = BASE_API_PORT + index;
    if (!usedApiPorts.has(apiPort) && !(await isPortInUse(apiPort))) {
      const p2pPort = BASE_P2P_PORT + index * 100;
      const wsPort = BASE_WS_PORT + index * 100;
      // Also check p2p port isn't in use
      if (!(await isPortInUse(p2pPort))) {
        return { port: p2pPort, wsPort, apiPort };
      }
    }
    index++;
  }
  throw new Error("No available ports found");
}

function agentLabel(apiPort: number): string {
  const idx = apiPort - BASE_API_PORT;
  const letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
  return `Agent ${letters[idx] || idx}`;
}

/**
 * Probe a port to check if an agentpay API is running there.
 */
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
 * GET /api/agents — list all agent processes (managed + externally discovered)
 */
export async function GET() {
  const managed = Array.from(agents.values()).map((a) => ({
    pid: a.pid,
    port: a.port,
    wsPort: a.wsPort,
    apiPort: a.apiPort,
    label: a.label,
    startedAt: a.startedAt,
    alive: !a.process.killed,
    external: false,
  }));

  const managedPorts = new Set(managed.map((a) => a.apiPort));

  // Discover external agents on default port range
  const SCAN_PORTS = Array.from({ length: 10 }, (_, i) => BASE_API_PORT + i);
  const externalChecks = SCAN_PORTS
    .filter((p) => !managedPorts.has(p))
    .map(async (apiPort) => {
      const alive = await probeAgentPort(apiPort);
      if (!alive) return null;
      return {
        pid: 0,
        port: 0,
        wsPort: 0,
        apiPort,
        label: agentLabel(apiPort),
        startedAt: 0,
        alive: true,
        external: true,
      };
    });

  const externalResults = await Promise.all(externalChecks);
  const external = externalResults.filter((x): x is NonNullable<typeof x> => x !== null);

  const list = [...managed, ...external].sort((a, b) => a.apiPort - b.apiPort);
  return NextResponse.json({ agents: list, count: list.length });
}

/**
 * POST /api/agents — start a new agent node
 * Body (optional): { apiPort?, port?, wsPort? }
 */
export async function POST(request: Request) {
  let body: { apiPort?: number; port?: number; wsPort?: number } = {};
  try {
    body = await request.json();
  } catch {
    // no body is fine — auto-assign ports
  }

  // Enforce hard cap
  if (agents.size >= MAX_AGENTS) {
    return NextResponse.json(
      { error: `Maximum agent limit reached (${MAX_AGENTS}). Stop some agents first.` },
      { status: 429 },
    );
  }

  const ports = await nextAvailablePorts();
  const apiPort = body.apiPort ?? ports.apiPort;
  const port = body.port ?? ports.port;
  const wsPort = body.wsPort ?? ports.wsPort;

  // Check if port already in use by us
  if (agents.has(apiPort)) {
    return NextResponse.json(
      { error: `Agent already running on API port ${apiPort}` },
      { status: 409 },
    );
  }

  const identityIdx = apiPort - BASE_API_PORT;
  const identityFile =
    identityIdx === 0
      ? "identity.key"
      : `identity${identityIdx + 1}.key`;
  const identityPath = `~/.agentic-payments/${identityFile}`;

  const label = agentLabel(apiPort);

  // Check if the API port is already in use (e.g. agent started externally)
  const portInUse = await isPortInUse(apiPort);
  if (portInUse) {
    return NextResponse.json(
      { error: `Port ${apiPort} is already in use (agent may be running externally)` },
      { status: 409 },
    );
  }

  try {
    const proc = spawn(
      "uv",
      [
        "run",
        "agentpay",
        "start",
        "--port", String(port),
        "--ws-port", String(wsPort),
        "--api-port", String(apiPort),
        "--identity-path", identityPath,
        "--log-level", "INFO",
      ],
      {
        cwd: PROJECT_ROOT,
        stdio: ["ignore", "pipe", "pipe"],
        detached: false,
      },
    );

    if (!proc.pid) {
      return NextResponse.json(
        { error: "Failed to spawn agent process" },
        { status: 500 },
      );
    }

    const agent: AgentProcess = {
      pid: proc.pid,
      port,
      wsPort,
      apiPort,
      identityPath,
      process: proc,
      startedAt: Date.now(),
      label,
    };

    agents.set(apiPort, agent);

    // Cleanup on exit
    proc.on("exit", () => {
      agents.delete(apiPort);
    });

    // Log stderr for debugging
    proc.stderr?.on("data", (data: Buffer) => {
      const line = data.toString().trim();
      if (line) {
        console.log(`[${label}] ${line}`);
      }
    });

    return NextResponse.json({
      agent: {
        pid: proc.pid,
        port,
        wsPort,
        apiPort,
        label,
        identityPath,
        startedAt: agent.startedAt,
      },
    }, { status: 201 });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}

/**
 * DELETE /api/agents — stop an agent by apiPort
 * Body: { apiPort: number }
 */
export async function DELETE(request: Request) {
  let body: { apiPort?: number };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Missing body" }, { status: 400 });
  }

  const apiPort = body.apiPort;
  if (!apiPort || !agents.has(apiPort)) {
    return NextResponse.json(
      { error: `No agent found on API port ${apiPort}` },
      { status: 404 },
    );
  }

  const agent = agents.get(apiPort)!;
  agent.process.kill("SIGTERM");
  agents.delete(apiPort);

  return NextResponse.json({
    stopped: { apiPort, pid: agent.pid, label: agent.label },
  });
}
