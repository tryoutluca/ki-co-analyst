"use client";

import AuthGuard from "@/components/shell/AuthGuard";
import AppHeader from "@/components/shell/AppHeader";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard>
      <div className="min-h-screen flex flex-col bg-paper">
        <AppHeader />
        <main className="flex-1">{children}</main>
      </div>
    </AuthGuard>
  );
}
