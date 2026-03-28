"use client";

import Navbar from "./Navbar";

export default function ClientShell({ children }: { children: React.ReactNode }) {
  return (
    <>
      <Navbar />
      <div className="relative z-10 pt-14">{children}</div>
    </>
  );
}
