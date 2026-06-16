"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { LayoutDashboard, Search, Clock, Settings, LogOut } from "lucide-react";
import { logout } from "@/lib/auth";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/dashboard", icon: LayoutDashboard, label: "Dashboard" },
  { href: "/analyse",   icon: Search,          label: "Analyse"   },
  { href: "/history",   icon: Clock,           label: "Historie"  },
  { href: "/settings",  icon: Settings,        label: "Einstellungen" },
];

export default function Sidebar() {
  const pathname = usePathname();
  const router   = useRouter();

  function handleLogout() {
    logout();
    router.push("/login");
  }

  return (
    <aside className="w-56 flex-shrink-0 flex flex-col"
           style={{ background: "#0a1628", borderRight: "1px solid rgba(201,168,76,0.15)" }}>

      {/* Nav */}
      <nav className="flex-1 pt-4 px-3 space-y-1">
        {NAV.map(({ href, icon: Icon, label }) => {
          const active = pathname === href || pathname.startsWith(href + "/");
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all",
                active
                  ? "text-[#c9a84c] border-l-2 border-[#c9a84c] pl-2.5"
                  : "text-slate-400 hover:text-white hover:bg-white/5"
              )}
              style={active ? { background: "rgba(201,168,76,0.12)" } : {}}
            >
              <Icon size={16} className="flex-shrink-0" />
              {label}
            </Link>
          );
        })}
      </nav>

      {/* Logout */}
      <div className="p-3 border-t" style={{ borderColor: "rgba(255,255,255,0.08)" }}>
        <button
          onClick={handleLogout}
          className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm w-full
                     text-slate-400 hover:text-white hover:bg-white/5 transition-all"
        >
          <LogOut size={16} />
          Abmelden
        </button>
      </div>
    </aside>
  );
}
