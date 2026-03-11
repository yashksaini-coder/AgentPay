"use client";

const stateConfig: Record<string, { bg: string; text: string; dot: string }> = {
  PROPOSED: { bg: "bg-warning-subtle", text: "text-warning", dot: "bg-warning" },
  OPEN: { bg: "bg-accent-subtle", text: "text-accent", dot: "bg-accent" },
  ACTIVE: { bg: "bg-success-subtle", text: "text-success", dot: "bg-success" },
  CLOSING: { bg: "bg-warning-subtle", text: "text-warning", dot: "bg-warning" },
  SETTLED: { bg: "bg-surface-overlay", text: "text-text-muted", dot: "bg-text-muted" },
  DISPUTED: { bg: "bg-danger-subtle", text: "text-danger", dot: "bg-danger" },
};

export default function StatusBadge({ state }: { state: string }) {
  const config = stateConfig[state] || stateConfig.SETTLED;

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-[var(--radius-badge)] text-[10px] font-medium tracking-wide uppercase ${config.bg} ${config.text}`}
    >
      <span
        className={`w-1.5 h-1.5 rounded-full ${config.dot} ${
          state === "ACTIVE" ? "animate-pulse-soft" : "opacity-50"
        }`}
      />
      {state}
    </span>
  );
}
