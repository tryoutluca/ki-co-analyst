"use client";

import { useState } from "react";
import AuthGuard from "@/components/shell/AuthGuard";
import Topbar   from "@/components/shell/Topbar";
import Sidebar  from "@/components/shell/Sidebar";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <AuthGuard>
      <div className="h-screen flex flex-col overflow-hidden">
        <Topbar onMenuClick={() => setSidebarOpen((v) => !v)} />
        <div className="flex flex-1 overflow-hidden">
          <Sidebar isOpen={sidebarOpen} onClose={() => setSidebarOpen(false)} />
          <main className="flex-1 overflow-y-auto bg-[#f7f8fa]">
            {children}
          </main>
        </div>
      </div>
    </AuthGuard>
  );
}
