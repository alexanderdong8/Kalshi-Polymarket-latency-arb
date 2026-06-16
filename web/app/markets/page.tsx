"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Activity, ArrowUpRight, FlaskConical, Radio } from "lucide-react";
import { api, pct } from "@/lib/api";
import type { MarketEvent } from "@/lib/types";
import { ModeDialog } from "@/components/mode-dialog";
import { EmptyState, PageHead, StatusBadge } from "@/components/ui";

export default function MarketsPage() {
  const events = useQuery({ queryKey: ["events"], queryFn: () => api<MarketEvent[]>("/events") });
  const [dialog, setDialog] = useState<{ event: MarketEvent; mode: "paper" | "live" | "backtest" } | null>(null);
  return (
    <>
      <PageHead eyebrow="02 / Approved universe" title="My Markets" />
      {events.data?.length ? (
        <div className="market-list">
          {events.data.map((event) => (
            <article className="market-row" key={event.id}>
              <div className="market-identity">
                <span className="event-index">{String(event.mappings.length).padStart(2, "0")}</span>
                <div><p>{event.category ?? "Approved event"}</p><h2>{event.name}</h2><small>{event.mappings.map((row) => row.name).join(" · ")}</small></div>
              </div>
              <div className="market-facts">
                <span><small>Net edge</small><b>{pct(event.ranking.executable_net_edge)}</b></span>
                <span><small>Depth</small><b>{event.ranking.fillable_depth ?? "Pending"}</b></span>
                <span><small>Historical</small><b>{pct(event.ranking.historical_suitability, true)}</b></span>
                <span><small>Modes</small><b>{event.active_modes.length ? event.active_modes.join(" + ") : "Watching"}</b></span>
              </div>
              <div className="market-actions">
                <button title="Start paper" onClick={() => setDialog({ event, mode: "paper" })}><FlaskConical size={16} /></button>
                <button title="Start live" className="risk" onClick={() => setDialog({ event, mode: "live" })}><Radio size={16} /></button>
                <button title="Run backtest" onClick={() => setDialog({ event, mode: "backtest" })}><Activity size={16} /></button>
                <Link href={`/events/${event.id}`} title="Inspect event"><ArrowUpRight size={16} /></Link>
              </div>
              <StatusBadge value="approved" />
            </article>
          ))}
        </div>
      ) : (
        <EmptyState title="Your approved watchlist is empty">Discover and review a complete event first. Individual contracts cannot be added here.</EmptyState>
      )}
      {dialog ? <ModeDialog {...dialog} onClose={() => setDialog(null)} /> : null}
    </>
  );
}
