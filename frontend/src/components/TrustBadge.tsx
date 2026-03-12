"use client";

interface TrustBadgeProps {
  score: number; // 0.0 to 1.0
  size?: "sm" | "md";
}

export default function TrustBadge({ score, size = "sm" }: TrustBadgeProps) {
  const pct = Math.round(score * 100);
  let color: string;
  let dotColor: string;

  if (score >= 0.7) {
    color = "bg-success/10 text-success border-success/20";
    dotColor = "bg-success";
  } else if (score >= 0.4) {
    color = "bg-warning/10 text-warning border-warning/20";
    dotColor = "bg-warning";
  } else {
    color = "bg-danger/10 text-danger border-danger/20";
    dotColor = "bg-danger";
  }

  const sizeClass = size === "sm" ? "text-[9px] px-1 py-px" : "text-[10px] px-1.5 py-0.5";

  return (
    <span className={`inline-flex items-center gap-1 rounded-md border font-mono ${color} ${sizeClass}`}>
      <span className={`inline-block w-1 h-1 rounded-full ${dotColor}`} />
      {pct}%
    </span>
  );
}
