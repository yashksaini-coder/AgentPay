"use client";

import { useState } from "react";
import type { AgentState } from "@/lib/useAgent";

type Tab = "channel" | "payment";

export default function ActionPanel({
  agentA,
  agentB,
}: {
  agentA: AgentState;
  agentB: AgentState;
}) {
  const [tab, setTab] = useState<Tab>("channel");

  return (
    <div className="glass-card rounded-[var(--radius-card)] overflow-hidden">
      {/* Tab bar */}
      <div className="flex border-b border-border-subtle">
        <TabButton
          active={tab === "channel"}
          onClick={() => setTab("channel")}
          icon={
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
            </svg>
          }
        >
          Open Channel
        </TabButton>
        <TabButton
          active={tab === "payment"}
          onClick={() => setTab("payment")}
          icon={
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 12 3.269 3.125A59.769 59.769 0 0 1 21.485 12 59.768 59.768 0 0 1 3.27 20.875L5.999 12Zm0 0h7.5" />
            </svg>
          }
        >
          Send Payment
        </TabButton>
      </div>

      <div className="p-5">
        {tab === "channel" ? (
          <OpenChannelPanel agentA={agentA} agentB={agentB} />
        ) : (
          <SendPaymentPanel agentA={agentA} agentB={agentB} />
        )}
      </div>
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
  icon,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
  icon: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex-1 flex items-center justify-center gap-2 text-xs py-3.5 font-medium transition-all duration-300 ${
        active
          ? "text-text-primary border-b-2 border-accent bg-accent-subtle"
          : "text-text-muted hover:text-text-secondary hover:bg-surface-overlay/30"
      }`}
    >
      {icon}
      {children}
    </button>
  );
}

function OpenChannelPanel({
  agentA,
  agentB,
}: {
  agentA: AgentState;
  agentB: AgentState;
}) {
  const [from, setFrom] = useState<"A" | "B">("A");
  const [deposit, setDeposit] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; msg: string } | null>(null);

  const sender = from === "A" ? agentA : agentB;
  const receiver = from === "A" ? agentB : agentA;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (
      !sender.online ||
      !receiver.online ||
      !receiver.identity?.peer_id ||
      !receiver.identity?.eth_address
    ) {
      setResult({ ok: false, msg: "Both agents must be online" });
      return;
    }

    setLoading(true);
    setResult(null);
    try {
      // Ensure the sender is connected to the receiver's libp2p address.
      // The advertised addrs may use 0.0.0.0 — replace with 127.0.0.1.
      const receiverAddrs = receiver.identity?.addrs ?? [];
      const tcpAddr = receiverAddrs.find(
        (a) => a.includes("/tcp/") && !a.includes("/ws")
      );
      if (tcpAddr) {
        // Replace 0.0.0.0 with 127.0.0.1 for local connectivity
        const connectableAddr = tcpAddr.replace("/ip4/0.0.0.0/", "/ip4/127.0.0.1/");
        // Ensure /p2p/ suffix with peer ID (addr may already include it)
        const fullAddr = connectableAddr.includes("/p2p/")
          ? connectableAddr
          : `${connectableAddr}/p2p/${receiver.identity!.peer_id}`;
        try {
          await sender.api.connectPeer(fullAddr);
        } catch {
          // May already be connected — continue
        }
      }

      const res = await sender.api.openChannel(
        receiver.identity.peer_id,
        receiver.identity.eth_address,
        parseInt(deposit),
      );
      setResult({
        ok: true,
        msg: `Channel opened: ${res.channel.channel_id.slice(0, 16)}...`,
      });
      setDeposit("");
      sender.refresh();
      receiver.refresh();
    } catch (e: unknown) {
      setResult({ ok: false, msg: e instanceof Error ? e.message : "Failed" });
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <FieldLabel>Direction</FieldLabel>
        <ToggleGroup
          options={[
            { value: "A", label: "A → B" },
            { value: "B", label: "B → A" },
          ]}
          selected={from}
          onChange={(v) => setFrom(v as "A" | "B")}
        />
      </div>

      <InputField
        label="Deposit (wei)"
        type="number"
        value={deposit}
        onChange={setDeposit}
        placeholder="1000000000000000000"
        required
        min="1"
      />

      <ResultMessage result={result} />

      <SubmitButton
        loading={loading}
        disabled={!sender.online || !receiver.online}
        variant="accent"
      >
        {loading ? "Opening..." : "Open Channel"}
      </SubmitButton>
    </form>
  );
}

function SendPaymentPanel({
  agentA,
  agentB,
}: {
  agentA: AgentState;
  agentB: AgentState;
}) {
  const [from, setFrom] = useState<"A" | "B">("A");
  const [channelId, setChannelId] = useState("");
  const [amount, setAmount] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; msg: string } | null>(null);

  const sender = from === "A" ? agentA : agentB;
  const activeChannels = sender.channels.filter((c) => c.state === "ACTIVE");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setResult(null);
    try {
      const res = await sender.api.sendPayment(channelId, parseInt(amount));
      setResult({
        ok: true,
        msg: `Sent! Nonce: ${res.voucher.nonce}, Cumulative: ${res.voucher.amount.toLocaleString()} wei`,
      });
      setAmount("");
      sender.refresh();
    } catch (e: unknown) {
      setResult({ ok: false, msg: e instanceof Error ? e.message : "Failed" });
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <FieldLabel>From</FieldLabel>
        <ToggleGroup
          options={[
            { value: "A", label: "Agent A" },
            { value: "B", label: "Agent B" },
          ]}
          selected={from}
          onChange={(v) => setFrom(v as "A" | "B")}
        />
      </div>

      {/* Channel selector */}
      <div>
        <FieldLabel>Channel</FieldLabel>
        {activeChannels.length > 0 ? (
          <select
            value={channelId}
            onChange={(e) => setChannelId(e.target.value)}
            required
            className="w-full bg-surface-overlay border border-border rounded-[var(--radius-input)] px-3 py-2.5 text-xs font-mono text-text-primary focus-ring focus:border-border-focus appearance-none transition-colors cursor-pointer"
          >
            <option value="">Select channel...</option>
            {activeChannels.map((ch) => (
              <option key={ch.channel_id} value={ch.channel_id}>
                {ch.channel_id.slice(0, 16)}... (
                {ch.remaining_balance.toLocaleString()} wei left)
              </option>
            ))}
          </select>
        ) : (
          <div className="text-xs text-text-muted py-3 text-center bg-surface-overlay/30 rounded-[var(--radius-input)] border border-border-subtle border-dashed">
            No active channels
          </div>
        )}
      </div>

      <InputField
        label="Amount (wei)"
        type="number"
        value={amount}
        onChange={setAmount}
        placeholder="100000000000000"
        required
        min="1"
      />

      <ResultMessage result={result} />

      <SubmitButton
        loading={loading}
        disabled={!channelId || !sender.online}
        variant="success"
      >
        {loading ? "Sending..." : "Send Payment"}
      </SubmitButton>
    </form>
  );
}

/* ---- Shared sub-components ---- */

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <label className="text-[10px] font-medium uppercase tracking-widest text-text-muted block mb-2">
      {children}
    </label>
  );
}

function ToggleGroup({
  options,
  selected,
  onChange,
}: {
  options: { value: string; label: string }[];
  selected: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="flex rounded-[var(--radius-button)] overflow-hidden border border-border bg-surface-overlay/30">
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onChange(opt.value)}
          className={`flex-1 text-xs py-2.5 font-medium transition-all duration-200 ${
            selected === opt.value
              ? "bg-accent-subtle text-accent border-b-2 border-accent"
              : "text-text-muted hover:text-text-secondary hover:bg-surface-hover"
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

function InputField({
  label,
  type,
  value,
  onChange,
  placeholder,
  required,
  min,
}: {
  label: string;
  type: string;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  required?: boolean;
  min?: string;
}) {
  return (
    <div>
      <FieldLabel>{label}</FieldLabel>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        required={required}
        min={min}
        className="w-full bg-surface-overlay border border-border rounded-[var(--radius-input)] px-3 py-2.5 text-sm font-mono text-text-primary placeholder:text-text-muted/40 focus-ring focus:border-border-focus transition-colors"
      />
    </div>
  );
}

function SubmitButton({
  children,
  loading,
  disabled,
  variant,
}: {
  children: React.ReactNode;
  loading: boolean;
  disabled: boolean;
  variant: "accent" | "success";
}) {
  const base =
    variant === "accent"
      ? "bg-accent hover:bg-accent-hover"
      : "bg-success hover:bg-success/80";

  return (
    <button
      type="submit"
      disabled={loading || disabled}
      className={`w-full ${base} disabled:opacity-30 disabled:cursor-not-allowed text-white text-sm font-medium py-3 rounded-[var(--radius-button)] transition-all duration-200 hover:shadow-lg active:scale-[0.98]`}
    >
      {children}
    </button>
  );
}

function ResultMessage({
  result,
}: {
  result: { ok: boolean; msg: string } | null;
}) {
  if (!result) return null;
  return (
    <div
      className={`text-xs rounded-[var(--radius-badge)] px-3 py-2.5 break-words border ${
        result.ok
          ? "bg-success-subtle text-success border-success/10"
          : "bg-danger-subtle text-danger border-danger/10"
      }`}
    >
      {result.msg}
    </div>
  );
}
