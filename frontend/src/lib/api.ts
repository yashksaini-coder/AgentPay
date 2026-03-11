const DEFAULT_API = "http://127.0.0.1:8080";

async function fetchApi<T>(base: string, path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${base}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(body.error || `API error: ${res.status}`);
  }
  return res.json();
}

// ---------- Types ----------

export interface Identity {
  peer_id: string | null;
  eth_address: string | null;
  addrs: string[];
  connected_peers?: number;
}

export interface Peer {
  peer_id: string;
  addrs?: string[];
}

export type ChannelState = "PROPOSED" | "OPEN" | "ACTIVE" | "CLOSING" | "SETTLED" | "DISPUTED";

export interface Channel {
  channel_id: string;
  sender: string;
  receiver: string;
  total_deposit: number;
  state: ChannelState;
  nonce: number;
  total_paid: number;
  remaining_balance: number;
  created_at: number;
  updated_at: number;
  peer_id: string;
}

export interface Voucher {
  channel_id: string;
  nonce: number;
  amount: number;
  timestamp: number;
  signature: string;
}

export interface Balance {
  address: string | null;
  total_deposited: number;
  total_paid: number;
  total_remaining: number;
  channel_count: number;
}

// ---------- API calls (parameterized by base URL) ----------

export function createApi(base: string = DEFAULT_API) {
  return {
    getHealth: () => fetchApi<{ status: string; version: string }>(base, "/health"),
    getIdentity: () => fetchApi<Identity>(base, "/identity"),
    getPeers: () => fetchApi<{ peers: Peer[]; count: number; connected: number }>(base, "/peers"),
    getChannels: () => fetchApi<{ channels: Channel[]; count: number }>(base, "/channels"),
    getChannel: (id: string) => fetchApi<Channel>(base, `/channels/${id}`),
    getBalance: () => fetchApi<Balance>(base, "/balance"),
    connectPeer: (multiaddr: string) =>
      fetchApi<{ status: string }>(base, "/connect", {
        method: "POST",
        body: JSON.stringify({ multiaddr }),
      }),
    openChannel: (peerId: string, receiver: string, deposit: number) =>
      fetchApi<{ channel: Channel }>(base, "/channels", {
        method: "POST",
        body: JSON.stringify({ peer_id: peerId, receiver, deposit }),
      }),
    closeChannel: (id: string) =>
      fetchApi<{ channel: Channel }>(base, `/channels/${id}/close`, { method: "POST" }),
    sendPayment: (channelId: string, amount: number) =>
      fetchApi<{ voucher: Voucher }>(base, "/pay", {
        method: "POST",
        body: JSON.stringify({ channel_id: channelId, amount }),
      }),
  };
}

export type Api = ReturnType<typeof createApi>;

// ---------- Formatting ----------

export function formatWei(wei: number): string {
  if (wei === 0) return "0";
  if (wei >= 1e18) return `${(wei / 1e18).toFixed(4)} ETH`;
  if (wei >= 1e9) return `${(wei / 1e9).toFixed(2)} Gwei`;
  return `${wei.toLocaleString()} wei`;
}

export function shortenId(id: string, chars: number = 8): string {
  if (id.length <= chars * 2 + 3) return id;
  return `${id.slice(0, chars)}...${id.slice(-chars)}`;
}

export function shortenAddr(addr: string): string {
  if (addr.length <= 13) return addr;
  return `${addr.slice(0, 6)}...${addr.slice(-4)}`;
}
