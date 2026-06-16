import AuthGuard from "@/components/shell/AuthGuard";
import Topbar   from "@/components/shell/Topbar";
import Sidebar  from "@/components/shell/Sidebar";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard>
      <div className="h-screen flex flex-col overflow-hidden">
        <Topbar />
        <div className="flex flex-1 overflow-hidden">
          <Sidebar />
          <main className="flex-1 overflow-y-auto bg-[#f7f8fa]">
            {children}
          </main>
        </div>
      </div>
    </AuthGuard>
  );
}
