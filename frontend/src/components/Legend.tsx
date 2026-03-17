"use client";

const items = [
  { color: "#7c6df0", label: "Agent Node" },
  { color: "#505068", label: "Discovered Peer" },
];

export default function Legend() {
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2 px-4 py-2.5">
      {items.map((item) => (
        <div key={item.label} className="flex items-center gap-2">
          <span
            className="w-2.5 h-2.5 rounded-full"
            style={{ backgroundColor: item.color, opacity: 0.8 }}
          />
          <span className="text-[10px] text-text-muted">{item.label}</span>
        </div>
      ))}

      <span className="w-px h-3 bg-border-subtle" />

      {/* P2P connection */}
      <div className="flex items-center gap-2">
        <svg width="20" height="4" className="shrink-0">
          <line x1="0" y1="2" x2="20" y2="2" stroke="rgba(255,255,255,0.15)" strokeWidth="1.5" />
        </svg>
        <span className="text-[10px] text-text-muted">P2P Connection</span>
      </div>

      {/* Channel health gradient: fresh → mid → depleted */}
      <div className="flex items-center gap-2">
        <svg width="24" height="4" className="shrink-0">
          <defs>
            <linearGradient id="lg-channel-health">
              <stop offset="0%" stopColor="#34d399" stopOpacity="0.7" />
              <stop offset="50%" stopColor="#fbbf24" stopOpacity="0.7" />
              <stop offset="100%" stopColor="#f87171" stopOpacity="0.7" />
            </linearGradient>
          </defs>
          <line x1="0" y1="2" x2="24" y2="2" stroke="url(#lg-channel-health)" strokeWidth="2.5" />
        </svg>
        <span className="text-[10px] text-text-muted">Channel Health</span>
      </div>

      <span className="w-px h-3 bg-border-subtle" />

      {/* Pulse ring indicator */}
      <div className="flex items-center gap-2">
        <svg width="16" height="16" className="shrink-0">
          <circle cx="8" cy="8" r="4" fill="none" stroke="#fbbf24" strokeWidth="1.5" opacity="0.7" />
          <circle cx="8" cy="8" r="7" fill="none" stroke="#fbbf24" strokeWidth="0.5" opacity="0.3" />
        </svg>
        <span className="text-[10px] text-text-muted">Payment Pulse</span>
      </div>

      <span className="w-px h-3 bg-border-subtle" />

      <span className="text-[10px] text-text-muted/40">
        Drag to pin · Double-click to unpin
      </span>
    </div>
  );
}
