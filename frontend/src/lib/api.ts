const DEFAULT_API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8080";

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
  eip191_bound?: boolean;
  verified_peers?: number;
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
  task_id?: string;
}

export interface Balance {
  address: string | null;
  total_deposited: number;
  total_paid: number;
  total_remaining: number;
  channel_count: number;
}

export interface RouteHop {
  peer_id: string;
  channel_id: string;
  amount: number;
  timeout: number;
}

export interface RouteInfo {
  hops: RouteHop[];
  total_amount: number;
  total_timeout: number;
  hop_count: number;
}

export interface RoutedPayment {
  status: string;
  payment_hash: string;
  preimage: string;
  route: RouteInfo;
  amount: number;
}

export interface NetworkGraphData {
  peers: string[];
  channels: { channel_id: string; peer_a: string; peer_b: string; capacity: number }[];
  peer_count: number;
  channel_count: number;
}

// ---------- New subsystem types ----------

export interface AgentCapability {
  service_type: string;
  price_per_call: number;
  description: string;
}

export interface DiscoveredAgent {
  peer_id: string;
  eth_address: string;
  capabilities: AgentCapability[];
  addrs: string[];
  last_seen: number;
}

export type NegotiationState = "proposed" | "countered" | "accepted" | "rejected" | "expired" | "channel_opened";

export interface NegotiationEvent {
  action: string;
  price: number;
  by: string;
  timestamp: number;
}

export interface Negotiation {
  negotiation_id: string;
  initiator: string;
  responder: string;
  service_type: string;
  proposed_price: number;
  current_price: number;
  channel_deposit: number;
  timeout: number;
  state: NegotiationState;
  channel_id: string | null;
  history: NegotiationEvent[];
  created_at: number;
}

export interface WalletPolicy {
  max_spend_per_tx: number;
  max_total_spend: number;
  rate_limit_per_min: number;
  peer_whitelist: string[];
  peer_blacklist: string[];
}

export interface PolicyStats {
  total_spent: number;
  payments_last_minute: number;
  policy: WalletPolicy;
}

export interface PeerReputation {
  peer_id: string;
  payments_sent: number;
  payments_received: number;
  payments_failed: number;
  htlcs_fulfilled: number;
  htlcs_cancelled: number;
  total_volume: number;
  avg_response_time: number;
  trust_score: number;
  total_interactions: number;
  first_seen: number;
}

export interface Receipt {
  receipt_id: string;
  channel_id: string;
  nonce: number;
  amount: number;
  timestamp: number;
  sender: string;
  receiver: string;
  previous_receipt_hash: string;
  receipt_hash: string;
  signature: string;
}

export interface GatedResource {
  path: string;
  price: number;
  description: string;
  payment_type: string;
}

// ---------- SLA, Pricing, Disputes, Chain types ----------

export interface SLATerms {
  max_latency_ms: number;
  min_availability: number;
  max_error_rate: number;
  min_throughput: number;
  penalty_rate: number;
  measurement_window: number;
  dispute_threshold: number;
}

export interface SLAViolation {
  channel_id: string;
  violation_type: string;
  measured_value: number;
  threshold_value: number;
  timestamp: number;
}

export interface SLAChannelStatus {
  channel_id: string;
  sla_terms: SLATerms | null;
  violations: SLAViolation[];
  compliant: boolean;
}

export interface PricingQuote {
  service_type: string;
  base_price: number;
  adjusted_price: number;
  trust_discount: number;
  congestion_premium: number;
  multiplier: number;
}

export interface PricingConfig {
  trust_discount_factor: number;
  congestion_premium_factor: number;
  min_price: number;
  max_price: number;
  congestion_threshold: number;
}

export type DisputeReason = "STALE_VOUCHER" | "SLA_VIOLATION" | "DOUBLE_SPEND" | "UNRESPONSIVE";
export type DisputeResolution = "PENDING" | "CHALLENGER_WINS" | "RESPONDER_WINS" | "SETTLED";

export interface Dispute {
  dispute_id: string;
  channel_id: string;
  challenger: string;
  responder: string;
  reason: DisputeReason;
  resolution: DisputeResolution;
  evidence_nonce: number;
  evidence_amount: number;
  slash_amount: number;
  created_at: number;
  resolved_at: number | null;
}

export interface ChainInfo {
  chain_type: string;
  ethereum?: { rpc_url: string };
  algorand?: { algod_url: string; app_id: number; network: string };
  filecoin?: { rpc_url: string; chain_id: number; network: string };
  storage?: { enabled: boolean; ipfs_api_url: string };
}

export interface ERC8004Identity {
  agent_id: number | null;
  eth_address: string;
  peer_id: string;
  agent_uri: string;
  registered_on_chain: boolean;
  chain_id: number;
  registration_tx: string | null;
  enabled: boolean;
}

export interface StorageStatus {
  enabled: boolean;
  healthy?: boolean;
  api_url?: string;
}

// ---------- New: Roles, Work Rounds, One-Shot, Error Codes ----------

export type AgentRoleType = "coordinator" | "worker" | "data_provider" | "validator" | "gateway";

export interface RoleAssignment {
  role: AgentRoleType;
  capabilities?: string[];
  max_concurrent_tasks?: number;
}

export interface WorkRound {
  round_id: string;
  coordinator_peer_id: string;
  task_type: string;
  required_role?: AgentRoleType;
  max_workers?: number;
  reward_per_worker?: number;
  assigned_workers: string[];
}

export interface OneshotPaymentResult {
  status: string;
  resource: string;
  amount: number;
  receiver: string;
  payer: string;
  settled_at: number;
}

export interface PaymentErrorResponse {
  error: string;
  error_code: number;
  detail?: string;
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
    sendPayment: (channelId: string, amount: number, taskId?: string) =>
      fetchApi<{ voucher: Voucher }>(base, "/pay", {
        method: "POST",
        body: JSON.stringify({ channel_id: channelId, amount, ...(taskId ? { task_id: taskId } : {}) }),
      }),
    routePayment: (destination: string, amount: number, knownChannels?: { channel_id: string; peer_a: string; peer_b: string; capacity: number }[]) =>
      fetchApi<{ payment: RoutedPayment }>(base, "/route-pay", {
        method: "POST",
        body: JSON.stringify({ destination, amount, known_channels: knownChannels }),
      }),
    findRoute: (destination: string, amount: number, knownChannels?: { channel_id: string; peer_a: string; peer_b: string; capacity: number }[]) =>
      fetchApi<{ route: RouteInfo }>(base, "/route", {
        method: "POST",
        body: JSON.stringify({ destination, amount, known_channels: knownChannels }),
      }),
    getGraph: () => fetchApi<NetworkGraphData>(base, "/graph"),

    // Discovery
    getDiscoveredAgents: (capability?: string) =>
      fetchApi<{ agents: DiscoveredAgent[]; count: number }>(base, `/discovery/agents${capability ? `?capability=${capability}` : ""}`),
    getDiscoveryResources: () =>
      fetchApi<{ providers: unknown[]; count: number }>(base, "/discovery/resources"),

    // Negotiations
    negotiate: (peerId: string, serviceType: string, proposedPrice: number, channelDeposit: number) =>
      fetchApi<{ negotiation: Negotiation }>(base, "/negotiate", {
        method: "POST",
        body: JSON.stringify({ peer_id: peerId, service_type: serviceType, proposed_price: proposedPrice, channel_deposit: channelDeposit }),
      }),
    getNegotiations: () =>
      fetchApi<{ negotiations: Negotiation[]; count: number }>(base, "/negotiations"),
    getNegotiation: (id: string) =>
      fetchApi<{ negotiation: Negotiation }>(base, `/negotiations/${id}`),
    counterNegotiation: (id: string, counterPrice: number) =>
      fetchApi<{ negotiation: Negotiation }>(base, `/negotiations/${id}/counter`, {
        method: "POST",
        body: JSON.stringify({ counter_price: counterPrice }),
      }),
    acceptNegotiation: (id: string) =>
      fetchApi<{ negotiation: Negotiation }>(base, `/negotiations/${id}/accept`, { method: "POST" }),
    rejectNegotiation: (id: string) =>
      fetchApi<{ negotiation: Negotiation }>(base, `/negotiations/${id}/reject`, { method: "POST" }),

    // Policies
    getPolicies: () => fetchApi<PolicyStats>(base, "/policies"),
    updatePolicies: (policy: Partial<WalletPolicy>) =>
      fetchApi<{ policy: WalletPolicy }>(base, "/policies", {
        method: "PUT",
        body: JSON.stringify(policy),
      }),

    // Reputation
    getReputation: () => fetchApi<{ peers: PeerReputation[]; count: number }>(base, "/reputation"),
    getPeerReputation: (peerId: string) =>
      fetchApi<{ reputation: PeerReputation }>(base, `/reputation/${peerId}`),

    // Receipts
    getReceipts: () =>
      fetchApi<{ channels: { channel_id: string; receipt_count: number; chain_valid: boolean }[]; count: number }>(base, "/receipts"),
    getChannelReceipts: (channelId: string) =>
      fetchApi<{ channel_id: string; receipts: Receipt[]; count: number; chain_valid: boolean }>(base, `/receipts/${channelId}`),

    // Gateway
    getGatewayResources: () => fetchApi<{ provider: unknown; resources: GatedResource[] }>(base, "/gateway/resources"),
    registerGatewayResource: (path: string, price: number, description?: string) =>
      fetchApi<{ resource: GatedResource }>(base, "/gateway/register", {
        method: "POST",
        body: JSON.stringify({ path, price, description }),
      }),

    // SLA
    getSLAViolations: () =>
      fetchApi<{ violations: SLAViolation[]; count: number }>(base, "/sla/violations"),
    getSLAChannels: () =>
      fetchApi<{ channels: SLAChannelStatus[] }>(base, "/sla/channels"),
    getSLAChannel: (channelId: string) =>
      fetchApi<SLAChannelStatus>(base, `/sla/channels/${channelId}`),

    // Pricing
    getPricingQuote: (serviceType: string, peerId?: string) =>
      fetchApi<{ quote: PricingQuote }>(base, "/pricing/quote", {
        method: "POST",
        body: JSON.stringify({ service_type: serviceType, peer_id: peerId }),
      }),
    getPricingConfig: () => fetchApi<{ config: PricingConfig }>(base, "/pricing/config"),
    updatePricingConfig: (config: Partial<PricingConfig>) =>
      fetchApi<{ config: PricingConfig }>(base, "/pricing/config", {
        method: "PUT",
        body: JSON.stringify(config),
      }),

    // Disputes
    getDisputes: (pendingOnly?: boolean) =>
      fetchApi<{ disputes: Dispute[]; count: number }>(base, `/disputes${pendingOnly ? "?pending_only=true" : ""}`),
    getDispute: (id: string) => fetchApi<{ dispute: Dispute }>(base, `/disputes/${id}`),
    scanDisputes: () => fetchApi<{ disputes_filed: number }>(base, "/disputes/scan", { method: "POST" }),
    fileDispute: (channelId: string, reason: DisputeReason) =>
      fetchApi<{ dispute: Dispute }>(base, `/channels/${channelId}/dispute`, {
        method: "POST",
        body: JSON.stringify({ reason }),
      }),

    // Chain info
    getChainInfo: () => fetchApi<ChainInfo>(base, "/chain"),

    // ERC-8004 Identity
    getERC8004Status: () => fetchApi<ERC8004Identity>(base, "/identity/erc8004"),
    registerERC8004: () => fetchApi<ERC8004Identity>(base, "/identity/erc8004/register", { method: "POST" }),
    lookupERC8004: (agentId: number) => fetchApi<ERC8004Identity>(base, `/identity/erc8004/lookup/${agentId}`),
    syncReputationOnchain: (peerId: string) =>
      fetchApi<{ tx_hash: string | null; synced: boolean }>(base, "/reputation/sync-onchain", {
        method: "POST",
        body: JSON.stringify({ peer_id: peerId }),
      }),

    // IPFS Storage
    getStorageStatus: () => fetchApi<StorageStatus>(base, "/storage/status"),

    // Roles
    getRole: () => fetchApi<{ role: RoleAssignment | null }>(base, "/role"),
    setRole: (role: AgentRoleType, capabilities?: string[], maxConcurrentTasks?: number) =>
      fetchApi<{ role: RoleAssignment }>(base, "/role", {
        method: "PUT",
        body: JSON.stringify({ role, capabilities, max_concurrent_tasks: maxConcurrentTasks }),
      }),
    clearRole: () => fetchApi<{ status: string }>(base, "/role", { method: "DELETE" }),

    // Work Rounds
    getWorkRounds: () => fetchApi<{ work_rounds: WorkRound[]; count: number }>(base, "/work-rounds"),
    createWorkRound: (roundId: string, taskType: string, rewardPerWorker?: number, maxWorkers?: number) =>
      fetchApi<{ work_round: WorkRound }>(base, "/work-rounds", {
        method: "POST",
        body: JSON.stringify({ round_id: roundId, task_type: taskType, reward_per_worker: rewardPerWorker, max_workers: maxWorkers }),
      }),

    // One-Shot Payment
    payOneshot: (resource: string, amount: number, receiver: string, payer?: string, signature?: string) =>
      fetchApi<OneshotPaymentResult>(base, "/gateway/pay-oneshot", {
        method: "POST",
        body: JSON.stringify({ resource, amount, receiver, payer, signature }),
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
