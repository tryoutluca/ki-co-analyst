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
    <header className="h-14 flex items-center justify-between px-4 md:px-6 border-b border-slate-200 bg-white">

      <div className="flex items-center gap-3">
        <button
          onClick={onMenuClick}
          className="lg:hidden p-1.5 -ml-1.5 rounded-md text-slate-400 hover:text-slate-900 hover:bg-slate-50"
          aria-label="Menü öffnen"
        >
          <Menu size={20} />
        </button>
        <Image src="/logo.png" alt="KI-Co-Analyst" width={26} height={26} className="rounded-md" />
        <span className="text-base font-semibold text-slate-900 tracking-tight">
          KI-Co-Analyst
        </span>
      </div>

      <div className="flex items-center gap-4 text-xs text-slate-400">
        <span className="hidden sm:block">{time}</span>
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold text-white"
               style={{ background: "#c9a84c" }}>
            {username.charAt(0).toUpperCase()}
          </div>
          <span className="font-medium text-slate-700 hidden sm:block">{username}</span>
        </div>
      </div>
    </header>
  );
}
