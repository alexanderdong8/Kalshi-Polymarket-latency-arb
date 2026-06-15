"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { api, money, pct } from "@/lib/api";
import type { BacktestJob, MarketEvent } from "@/lib/types";
import { EmptyState, Metric, PageHead, Progress, StatusBadge } from "@/components/ui";
import { MarketChart } from "@/components/market-chart";

export default function BacktestsPage() {
  const client = useQueryClient();
  const events = useQuery({ queryKey: ["events"], queryFn: () => api<MarketEvent[]>("/events") });
  const jobs = useQuery({ queryKey: ["backtests"], queryFn: () => api<BacktestJob[]>("/backtests") });
  const [eventId, setEventId] = useState("");
  const [cash, setCash] = useState(1000);
  const run = useMutation({
    mutationFn: () => api("/backtests", { method: "POST", body: JSON.stringify({ event_id: eventId, starting_cash: cash }) }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["backtests"] }),
  });
  const selected = jobs.data?.[0];
  const result = selected?.result?.results?.[0];
  return (
    <>
      <PageHead eyebrow="05 / Historical laboratory" title="Backtests" description="Replay the Python strategy against PMXT Kalshi and international Polymarket L2. Every latency and fill model remains visible." />
      <section className="run-bar">
        <label>Approved event<select value={eventId} onChange={(event) => setEventId(event.target.value)}><option value="">Choose an event</option>{events.data?.map((event) => <option value={event.id} key={event.id}>{event.name}</option>)}</select></label>
        <label>Starting bankroll<div className="money-input"><span>$</span><input type="number" min="1" value={cash} onChange={(event) => setCash(Number(event.target.value))} /></div></label>
        <button className="button primary" disabled={!eventId || run.isPending} onClick={() => run.mutate()}><Play size={15} /> Run replay</button>
      </section>
      {selected ? (
        <>
          <section className="job-strip"><div><strong>{selected.event_name}</strong><StatusBadge value={selected.status} /></div><Progress value={selected.progress} /><small>{selected.result?.venue_split ?? "Validating overlapping L2 and fee coverage"}</small></section>
          {selected.unavailable_reasons.length ? <div className="warning-box">{selected.unavailable_reasons.map((reason) => <p key={reason}>{reason}</p>)}</div> : null}
          <div className="metrics-grid">
            <Metric label="Starting cash" value={money(selected.starting_cash)} />
            <Metric label="Ending cash" value={money(result?.ending_cash)} tone="positive" />
            <Metric label="Money gained" value={money(result?.total_money_gained)} tone="positive" />
            <Metric label="ROI" value={pct(Number(result?.roi ?? 0))} detail="Selected first delay/fill result" />
          </div>
          <section className="panel chart-panel"><MarketChart title="Equity curve / playback" yTitle="Portfolio value" traces={[{ x: [0, 1], y: [selected.starting_cash, Number(result?.ending_cash ?? selected.starting_cash)], type: "scatter", mode: "lines+markers", name: "Replay equity", line: { color: "#0d684c", width: 3 } }]} /></section>
          {selected.result?.results ? <section className="panel table-panel"><div className="panel-title"><div><p className="eyebrow">Latency matrix</p><h2>Fill assumptions</h2></div></div><div className="data-table"><div className="data-row backtest-row data-head"><span>Delay</span><span>Fill model</span><span>Ending cash</span><span>Gain</span><span>ROI</span></div>{selected.result.results.map((row, index) => <div className="data-row backtest-row" key={index}><span>{row.delay_ms} ms</span><span>{row.fill_model}</span><span>{money(row.ending_cash)}</span><span>{money(row.total_money_gained)}</span><span>{pct(Number(row.roi))}</span></div>)}</div></section> : null}
        </>
      ) : <EmptyState title="No historical runs">Choose an approved event. Unavailable PMXT coverage is reported precisely instead of replaced with proxy data.</EmptyState>}
    </>
  );
}
