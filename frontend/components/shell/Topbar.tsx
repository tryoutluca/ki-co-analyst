"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import { Menu } from "lucide-react";
import { getUsername } from "@/lib/auth";

interface TopbarProps {
  onMenuClick?: () => void;
}

export default function Topbar({ onMenuClick }: TopbarProps) {
  const [username, setUsername] = useState("");
  const [time, setTime]         = useState("");

  useEffect(() => {
    setUsername(getUsername());
    const tick = () => setTime(new Date().toLocaleString("de-CH",
      { day:"2-digit", month:"2-digit", year:"numeric", hour:"2-digit", minute:"2-digit" }));
    tick();
    const id = setInterval(tick, 30_000);
    return () => clearInterval(id);
  }, []);

  return (
    <header className="h-14 flex items-center justify-between px-4 md:px-6 border-b"
            style={{ background: "#0a1628", borderColor: "rgba(201,168,76,0.2)" }}>

      <div className="flex items-center gap-3">
        <button
          onClick={onMenuClick}
          className="lg:hidden p-1.5 -ml-1.5 rounded-md text-slate-300 hover:text-white hover:bg-white/5"
          aria-label="Menü öffnen"
        >
          <Menu size={20} />
        </button>
        <Image src="/logo.png" alt="KI-Co-Analyst" width={28} height={28} className="rounded-md" />
        <span className="font-serif text-lg font-bold text-white">
          KI-Co<span style={{ color: "#c9a84c" }}>·</span>Analyst
        </span>
        <span className="hidden md:block text-xs tracking-widest uppercase px-2 py-0.5 rounded"
              style={{ color: "#8a9bb0", border: "1px solid rgba(255,255,255,0.1)" }}>
          Research Platform
        </span>
      </div>

      <div className="flex items-center gap-4 text-xs" style={{ color: "#8a9bb0" }}>
        <span className="hidden sm:block">{time}</span>
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold text-white"
               style={{ background: "#c9a84c" }}>
            {username.charAt(0).toUpperCase()}
          </div>
          <span className="font-medium text-white hidden sm:block">{username}</span>
        </div>
      </div>
    </header>
  );
}
