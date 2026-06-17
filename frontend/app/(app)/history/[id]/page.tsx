"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { getHistoryItem } from "@/lib/api";
import MemoViewer from "@/components/memo/MemoViewer";
import { ArrowLeft } from "lucide-react";

export default function HistoryDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router  = useRouter();
  const [data, setData]     = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (id) getHistoryItem(id).then(setData).finally(() => setLoading(false));
  }, [id]);

  if (loading) return (
    <div className="flex items-center justify-center h-64 text-sm text-slate-400">
      Lade Analyse…
    </div>
  );
  if (!data) return (
    <div className="flex items-center justify-center h-64 text-sm text-slate-400">
      Analyse nicht gefunden.
    </div>
  );

  return (
    <div className="max-w-7xl mx-auto px-6 py-8 space-y-6">
      <button
        onClick={() => router.back()}
        className="flex items-center gap-2 text-sm text-slate-500 hover:text-slate-800 transition-colors">
        <ArrowLeft size={15} /> Zurück zur Historie
      </button>
      <MemoViewer data={data} histId={id} />
    </div>
  );
}
