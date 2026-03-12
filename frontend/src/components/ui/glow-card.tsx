"use client";

import { useRef, useState, useCallback } from "react";
import { motion } from "framer-motion";

/**
 * Card with radial glow that follows the cursor — inspired by 21st.dev "Card Spotlight".
 */
export function GlowCard({
  children,
  className = "",
  glowColor = "rgba(124,109,240,0.08)",
}: {
  children: React.ReactNode;
  className?: string;
  glowColor?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const [hover, setHover] = useState(false);

  const handleMove = useCallback((e: React.MouseEvent) => {
    if (!ref.current) return;
    const rect = ref.current.getBoundingClientRect();
    setPos({ x: e.clientX - rect.left, y: e.clientY - rect.top });
  }, []);

  return (
    <div
      ref={ref}
      onMouseMove={handleMove}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      className={`relative overflow-hidden rounded-2xl border border-white/[0.06] bg-gradient-to-br from-white/[0.025] to-white/[0.01] transition-all duration-300 ${className}`}
    >
      {/* Cursor-following radial glow */}
      <motion.div
        className="pointer-events-none absolute -inset-px z-0"
        animate={{ opacity: hover ? 1 : 0 }}
        transition={{ duration: 0.3 }}
        style={{
          background: `radial-gradient(400px circle at ${pos.x}px ${pos.y}px, ${glowColor}, transparent 70%)`,
        }}
      />
      <div className="relative z-10">{children}</div>
    </div>
  );
}
