"use client";

const items = [
  { color: "#7c6df0", label: "Agent Node" },
  { color: "#505068", label: "Discovered Peer" },
];

const lines = [
  { style: "solid", color: "rgba(255,255,255,0.15)", label: "P2P Connection" },
  { style: "gradient", colors: ["#fbbf24", "#60a5fa", "#34d399"], label: "Payment Channel" },
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

      {lines.map((line) => (
        <div key={line.label} className="flex items-center gap-2">
          <svg width="20" height="4" className="shrink-0">
            {line.style === "solid" && (
              <line x1="0" y1="2" x2="20" y2="2" stroke={line.color} strokeWidth="1.5" />
            )}
            {line.style === "gradient" && (
              <>
                <defs>
                  <linearGradient id="lg-channel-legend">
                    <stop offset="0%" stopColor="#fbbf24" stopOpacity="0.8" />
                    <stop offset="50%" stopColor="#60a5fa" stopOpacity="0.8" />
                    <stop offset="100%" stopColor="#34d399" stopOpacity="0.8" />
                  </linearGradient>
                </defs>
                <line x1="0" y1="2" x2="20" y2="2" stroke="url(#lg-channel-legend)" strokeWidth="2" />
              </>
            )}
          </svg>
          <span className="text-[10px] text-text-muted">{line.label}</span>
        </div>
      ))}

      <span className="w-px h-3 bg-border-subtle" />

      {/* Transfer pulse indicator */}
      <div className="flex items-center gap-2">
        <svg width="16" height="16" className="shrink-0">
          <circle cx="8" cy="8" r="4" fill="none" stroke="#fb923c" strokeWidth="2" opacity="0.6" />
          <circle cx="8" cy="8" r="7" fill="none" stroke="#fb923c" strokeWidth="0.5" opacity="0.3" />
        </svg>
        <span className="text-[10px] text-text-muted">Transfer Pulse</span>
      </div>

      <span className="w-px h-3 bg-border-subtle" />

      <span className="text-[10px] text-text-muted/40">
        Drag to pin · Double-click to unpin
      </span>
    </div>
  );
}
