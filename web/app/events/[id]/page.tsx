"use client";

import { use, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, pct } from "@/lib/api";
import type { MarketEvent } from "@/lib/types";
import { MarketChart } from "@/components/market-chart";
import { EmptyState, Metric, PageHead, StatusBadge } from "@/components/ui";

export default function EventDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const event = useQuery({ queryKey: ["event", id], queryFn: () => api<MarketEvent>(`/events/${id}`) });
  const [outcome, setOutcome] = useState("");
  const selected = outcome || event.data?.mappings[0]?.name || "";
  const worker = event.data?.workers?.find((row) => ["running", "starting"].includes(row.status));
  const state = worker?.state ?? {};
  const books = state.books as Record<string, { bids?: [string, string][]; asks?: [string, string][] }> | undefined;
  const orderbook = useMemo(() => {
    const kalshi = books?.[`kalshi:${selected}`] ?? {};
    const polymarket = books?.[`polymarket_us:${selected}`] ?? {};
    return { kalshi, polymarket };
  }, [books, selected]);
  if (event.isLoading) return <p>Loading event...</p>;
  if (!event.data) return <EmptyState title="Event unavailable">The approved event could not be loaded.</EmptyState>;
  const evaluation = state.evaluation as Record<string, string> | null | undefined;
  return (
    <>
      <PageHead eyebrow={`${event.data.category ?? "Event"} / approved ${event.data.approval_version.slice(0, 8)}`} title={event.data.name} description={event.data.description || "Complete multi-outcome event across Kalshi and Polymarket US."} actions={<StatusBadge value={worker?.mode ?? "watching"} />} />
      <div className="metrics-grid">
        <Metric label="Basket cost" value={evaluation?.basket_cost ? `$${evaluation.basket_cost}` : "Waiting"} />
        <Metric label="Entry threshold" value={evaluation?.threshold ? `$${evaluation.threshold}` : "$0.98"} />
        <Metric label="$1 payout edge" value={evaluation?.edge ? `$${evaluation.edge}` : "Waiting"} tone="positive" />
        <Metric label="Mapping confidence" value={pct(event.data.llm_confidence)} detail={`${event.data.mappings.length} complete outcomes`} />
      </div>
      <section className="outcome-tabs" aria-label="Outcomes">{event.data.mappings.map((mapping) => <button className={selected === mapping.name ? "active" : ""} onClick={() => setOutcome(mapping.name)} key={mapping.name}>{mapping.name}</button>)}</section>
      <div className="detail-grid">
        <section className="panel chart-panel"><MarketChart title={`${selected} venue price`} traces={[{ x: [1, 2, 3, 4, 5], y: [0.48, 0.49, 0.485, 0.5, 0.5], type: "scatter", mode: "lines", name: "Kalshi", line: { color: "#15251e", width: 2 } }, { x: [1, 2, 3, 4, 5], y: [0.47, 0.475, 0.49, 0.495, 0.49], type: "scatter", mode: "lines", name: "Polymarket US", line: { color: "#2a8066", width: 2 } }]} /></section>
        <section className="panel orderbook-panel"><div className="panel-title"><div><p className="eyebrow">Full L2 depth</p><h2>{selected}</h2></div></div><div className="book-columns"><OrderBook name="Kalshi" book={orderbook.kalshi} /><OrderBook name="Polymarket US" book={orderbook.polymarket} /></div></section>
      </div>
      <section className="panel mapping-detail"><div className="panel-title"><div><p className="eyebrow">Settlement map</p><h2>Reviewed outcome pairings</h2></div></div>{event.data.mappings.map((mapping) => <div className="rule-pair" key={mapping.name}><h3>{mapping.name}</h3><div><span>Kalshi · {mapping.kalshi_ticker}</span><p>{mapping.kalshi_rules || mapping.kalshi_title}</p></div><div><span>Polymarket US · {mapping.polymarket_us_slug}</span><p>{mapping.polymarket_rules || mapping.polymarket_title}</p></div></div>)}</section>
    </>
  );
}

function OrderBook({ name, book }: { name: string; book: { bids?: [string, string][]; asks?: [string, string][] } }) {
  const rows = [...(book.asks ?? []).slice(0, 5).reverse().map((row) => ({ row, side: "ask" })), ...(book.bids ?? []).slice(0, 5).map((row) => ({ row, side: "bid" }))];
  return <div className="book"><h3>{name}</h3><div className="book-head"><span>Price</span><span>Size</span></div>{rows.length ? rows.map(({ row, side }, index) => <div className={`book-row ${side}`} key={`${side}-${index}`}><span>{Number(row[0]).toFixed(3)}</span><span>{row[1]}</span></div>) : <p className="book-empty">Awaiting a running market stream</p>}</div>;
}
