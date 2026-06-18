"use client";

import { use, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Data } from "plotly.js";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { MarketEvent, RuntimeBook, Worker } from "@/lib/types";
import { subscribeLocalStream } from "@/lib/ws";
import {
  appendHistory,
  buildTraces,
  midpoint,
  quote,
  type HistoryPoint,
  type SideKey,
  type WindowKey,
} from "@/lib/event-detail-state";
import { MarketChart } from "@/components/market-chart";
import { EmptyState, Metric, PageHead, StatusBadge } from "@/components/ui";

export default function EventDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [selectedOutcome, setSelectedOutcome] = useState("");
  const [windowKey, setWindowKey] = useState<WindowKey>("30m");
  const [liveWorker, setLiveWorker] = useState<Worker | null>(null);
  const [lastStreamAt, setLastStreamAt] = useState<number | null>(null);
  const [streamFresh, setStreamFresh] = useState(false);
  const [history, setHistory] = useState<HistoryPoint[]>([]);
  const pendingWorker = useRef<Worker | null>(null);
  const flushTimer = useRef<number | null>(null);
  const staleTimer = useRef<number | null>(null);

  const event = useQuery({
    queryKey: ["event", id],
    queryFn: () => api<MarketEvent>(`/events/${id}`),
    refetchInterval: streamFresh ? false : 5000,
  });

  const snapshotWorker = event.data?.workers?.find((row) =>
    ["running", "starting"].includes(row.status),
  );
  const worker = liveWorker ?? snapshotWorker;
  const state = worker?.state ?? {};
  const books = useMemo(() => state.books ?? {}, [state.books]);
  const selected = selectedOutcome || event.data?.mappings[0]?.name || "";
  const orderbook = useMemo(
    () => ({
      kalshi: books[`kalshi:${selected}`],
      polymarket_us: books[`polymarket_us:${selected}`],
    }),
    [books, selected],
  );

  const ingestWorker = useCallback((nextWorker: Worker) => {
    setLiveWorker(nextWorker);
    setLastStreamAt(Date.now());
    setStreamFresh(true);
    if (staleTimer.current !== null) window.clearTimeout(staleTimer.current);
    staleTimer.current = window.setTimeout(() => setStreamFresh(false), 5000);
    setHistory((current) => appendHistory(current, nextWorker.state));
  }, []);

  useEffect(() => {
    return subscribeLocalStream<Worker>(["worker.updated"], (message) => {
      if (message.topic !== "worker.updated" || message.payload.event_id !== id) return;
      pendingWorker.current = message.payload;
      if (flushTimer.current !== null) return;
      flushTimer.current = window.setTimeout(() => {
        flushTimer.current = null;
        const latest = pendingWorker.current;
        pendingWorker.current = null;
        if (latest) ingestWorker(latest);
      }, 250);
    });
  }, [id, ingestWorker]);

  useEffect(() => {
    return () => {
      if (flushTimer.current !== null) window.clearTimeout(flushTimer.current);
      if (staleTimer.current !== null) window.clearTimeout(staleTimer.current);
    };
  }, []);

  const traces = useMemo(
    () => buildTraces(history, selected, windowKey),
    [history, selected, windowKey],
  );
  const latestBooks = useMemo(
    () => [orderbook.kalshi, orderbook.polymarket_us].filter(Boolean) as RuntimeBook[],
    [orderbook],
  );
  const maxAgeMs = latestBooks.length
    ? Math.max(...latestBooks.map((book) => Number(book.age_ms ?? 0)))
    : null;
  const stale = maxAgeMs !== null && maxAgeMs > 5000;
  const evaluation = state.evaluation;
  const health = state.stream_health ?? {};

  if (event.isLoading) return <p>Loading event...</p>;
  if (!event.data) return <EmptyState title="Event unavailable">The approved event could not be loaded.</EmptyState>;

  return (
    <>
      <PageHead
        eyebrow={`${event.data.category ?? "Event"} / approved ${event.data.approval_version.slice(0, 8)}`}
        title={event.data.name}
        description={event.data.description || "Complete multi-outcome event across Kalshi and Polymarket US."}
        actions={<StatusBadge value={worker?.mode ?? "watching"} />}
      />
      <div className="metrics-grid">
        <Metric label="Basket cost" value={evaluation?.basket_cost ? `$${evaluation.basket_cost}` : "Waiting"} />
        <Metric label="Entry threshold" value={evaluation?.threshold ? `$${evaluation.threshold}` : "$0.98"} />
        <Metric label="$1 payout edge" value={evaluation?.edge ? `$${evaluation.edge}` : "Waiting"} tone="positive" />
        <Metric
          label="Book freshness"
          value={maxAgeMs === null ? "Waiting" : `${Math.round(maxAgeMs)}ms`}
          detail={stale ? "Stale stream warning" : `${event.data.mappings.length} complete outcomes`}
          tone={stale ? "risk" : "positive"}
        />
      </div>
      <section className="outcome-tabs" aria-label="Outcomes">
        {event.data.mappings.map((mapping) => (
          <button
            className={selected === mapping.name ? "active" : ""}
            onClick={() => setSelectedOutcome(mapping.name)}
            key={mapping.name}
          >
            {mapping.name}
          </button>
        ))}
      </section>
      <section className="price-strip">
        <PriceTile label="Kalshi YES" book={orderbook.kalshi} side="yes" />
        <PriceTile label="Kalshi NO" book={orderbook.kalshi} side="no" />
        <PriceTile label="Polymarket US YES" book={orderbook.polymarket_us} side="yes" />
        <PriceTile label="Polymarket US NO" book={orderbook.polymarket_us} side="no" />
      </section>
      <div className="detail-grid">
        <section className="panel chart-panel event-chart-panel">
          <div className="panel-title">
            <div><p className="eyebrow">Live price history</p><h2>{selected}</h2></div>
            <div className="window-toggle" aria-label="Chart window">
              {(["30m", "3h"] as WindowKey[]).map((value) => (
                <button
                  className={windowKey === value ? "active" : ""}
                  onClick={() => setWindowKey(value)}
                  key={value}
                >
                  {value}
                </button>
              ))}
            </div>
          </div>
          <MarketChart
            title={`${selected} YES / NO prices`}
            traces={traces.length ? traces : emptyTrace()}
            height={540}
          />
          <div className="stream-health">
            <span>Kalshi updates <b>{health.kalshi_updates ?? 0}</b></span>
            <span>Polymarket US updates <b>{health.polymarket_us_updates ?? 0}</b></span>
            <span>Reconnects <b>{health.reconnects ?? 0}</b></span>
            <span>Sequence gaps <b>{health.sequence_gaps ?? 0}</b></span>
            <span>Last stream <b>{lastStreamAt ? new Date(lastStreamAt).toLocaleTimeString() : "REST"}</b></span>
          </div>
        </section>
        <section className="panel orderbook-panel">
          <div className="panel-title"><div><p className="eyebrow">Full L2 depth</p><h2>{selected}</h2></div></div>
          <div className="venue-book-grid">
            <VenueBooks name="Kalshi" book={orderbook.kalshi} />
            <VenueBooks name="Polymarket US" book={orderbook.polymarket_us} />
          </div>
        </section>
      </div>
      {!worker ? (
        <EmptyState title="No running session">
          Start paper or live trading from My Markets to stream this event. Opening this page does not auto-start monitoring.
        </EmptyState>
      ) : null}
      <section className="panel mapping-detail">
        <div className="panel-title"><div><p className="eyebrow">Settlement map</p><h2>Reviewed outcome pairings</h2></div></div>
        {event.data.mappings.map((mapping) => (
          <div className="rule-pair" key={mapping.name}>
            <h3>{mapping.name}</h3>
            <div><span>Kalshi · {mapping.kalshi_ticker}</span><p>{mapping.kalshi_rules || mapping.kalshi_title}</p></div>
            <div><span>Polymarket US · {mapping.polymarket_us_slug}</span><p>{mapping.polymarket_rules || mapping.polymarket_title}</p></div>
          </div>
        ))}
      </section>
    </>
  );
}

function PriceTile({ label, book, side }: { label: string; book?: RuntimeBook; side: SideKey }) {
  const bid = quote(book, side, "bid");
  const ask = quote(book, side, "ask");
  return (
    <div className="price-tile">
      <span>{label}</span>
      <b>{formatQuote(midpoint(bid, ask) ?? ask ?? bid)}</b>
      <small>Bid {formatQuote(bid)} · Ask {formatQuote(ask)} · {formatAge(book?.age_ms)}</small>
    </div>
  );
}

function VenueBooks({ name, book }: { name: string; book?: RuntimeBook }) {
  return (
    <div className="venue-book">
      <h3>{name}</h3>
      <div className="side-book-grid">
        <OrderBook name="YES" bids={book?.yes_bids ?? book?.bids} asks={book?.yes_asks ?? book?.asks} />
        <OrderBook name="NO" bids={book?.no_bids} asks={book?.no_asks} />
      </div>
    </div>
  );
}

function OrderBook({
  name,
  bids,
  asks,
}: {
  name: string;
  bids?: [string, string][];
  asks?: [string, string][];
}) {
  const rows = [
    ...(asks ?? []).slice(0, 5).reverse().map((row) => ({ row, side: "ask" })),
    ...(bids ?? []).slice(0, 5).map((row) => ({ row, side: "bid" })),
  ];
  return (
    <div className="book side-book">
      <h4>{name}</h4>
      <div className="book-head"><span>Price</span><span>Size</span></div>
      {rows.length ? rows.map(({ row, side }, index) => (
        <div className={`book-row ${side}`} key={`${side}-${index}`}>
          <span>{Number(row[0]).toFixed(3)}</span><span>{row[1]}</span>
        </div>
      )) : <p className="book-empty">Awaiting stream</p>}
    </div>
  );
}

function formatQuote(value: number | null | undefined) {
  return value === null || value === undefined ? "Waiting" : value.toFixed(3);
}

function formatAge(value: number | undefined) {
  if (value === undefined) return "No stream";
  if (value < 1000) return `${Math.round(value)}ms old`;
  return `${(value / 1000).toFixed(1)}s old`;
}

function emptyTrace(): Data[] {
  return [
    {
      x: [],
      y: [],
      type: "scatter",
      mode: "lines",
      name: "Awaiting live stream",
      line: { color: "#0d684c", width: 2 },
    },
  ];
}
