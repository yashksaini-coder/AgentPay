"use client";

import { useState, useRef, useEffect } from "react";
import { motion } from "framer-motion";

/**
 * Tabs with sliding background indicator — inspired by 21st.dev "Animated Tabs".
 */
export function AnimatedTabs({
  tabs,
  defaultTab,
  onChange,
  className = "",
}: {
  tabs: { id: string; label: string; icon?: React.ReactNode }[];
  defaultTab?: string;
  onChange?: (id: string) => void;
  className?: string;
}) {
  const [active, setActive] = useState(defaultTab ?? tabs[0]?.id ?? "");
  const containerRef = useRef<HTMLDivElement>(null);
  const [indicator, setIndicator] = useState({ left: 0, width: 0 });

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const activeEl = container.querySelector(`[data-tab="${active}"]`) as HTMLElement | null;
    if (activeEl) {
      setIndicator({ left: activeEl.offsetLeft, width: activeEl.offsetWidth });
    }
  }, [active]);

  return (
    <div ref={containerRef} className={`relative flex rounded-lg bg-surface-overlay/50 p-0.5 ${className}`}>
      {/* Sliding background */}
      <motion.div
        className="absolute top-0.5 bottom-0.5 rounded-md bg-white/[0.08]"
        initial={false}
        animate={{ left: indicator.left, width: indicator.width }}
        transition={{ type: "spring", stiffness: 400, damping: 30 }}
      />
      {tabs.map((tab) => (
        <button
          key={tab.id}
          data-tab={tab.id}
          onClick={() => {
            setActive(tab.id);
            onChange?.(tab.id);
          }}
          className={`relative z-10 flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-medium rounded-md transition-colors ${
            active === tab.id ? "text-text-primary" : "text-text-muted hover:text-text-secondary"
          }`}
        >
          {tab.icon}
          {tab.label}
        </button>
      ))}
    </div>
  );
}
