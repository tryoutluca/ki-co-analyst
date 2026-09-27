"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { getHistoryItem } from "@/lib/api";
import MemoViewer from "@/components/memo/MemoViewer";

export default function HistoryDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [data, setData]       = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (id) getHistoryItem(id).then(setData).catch(() => setData(null)).finally(() => setLoading(false));
  }, [id]);

  return (
    <div className="flex flex-col">
      <div className="px-5 md:px-14 pt-6">
        <Link href="/history" className="font-mono text-[11px] tracking-[0.1em] no-underline">← HISTORIE</Link>
      </div>
      {loading ? (
        <div className="px-5 md:px-14 py-16 text-sm text-muted">Lade Analyse …</div>
      ) : !data ? (
        <div className="px-5 md:px-14 py-16 font-display text-3xl">Analyse nicht gefunden.</div>
      ) : (
        <MemoViewer data={data} histId={id} />
      )}
    </div>
  );
}
