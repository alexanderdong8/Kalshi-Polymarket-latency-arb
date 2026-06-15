"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pause, SquareArrowOutUpRight } from "lucide-react";
import { api, age, money } from "@/lib/api";
import type { Worker } from "@/lib/types";
import { EmptyState, Metric, PageHead, StatusBadge } from "@/components/ui";
import { MarketChart } from "./market-chart";

export function WorkersPage({ mode }: { mode: "paper" | "live" }) {
  const client = useQueryClient();
  const workers = useQuery({
    queryKey: ["workers", mode],
    queryFn: () => api<Worker[]>(`/workers?mode=${mode}`),
  });
  const stop = useMutation({
    mutationFn: (id: string) => api(`/workers/${id}/stop`, { method: "POST" }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["workers"] }),
  });
  const active = (workers.data ?? []).filter((row) => ["starting", "running"].includes(row.status));
  const total = active.reduce((sum, row) => sum + row.budget, 0);
  const liveBalances = active.reduce(
    (sum, row) => {
      const preview = row.state.startup_preview as
        | { reconciliation?: { kalshi_balance?: string; polymarket_us_balance?: string } }
        | undefined;
      return sum + Number(preview?.reconciliation?.kalshi_balance ?? 0) + Number(preview?.reconciliation?.polymarket_us_balance ?? 0);
    },
    0,
  );
  return (
    <>
      <PageHead
        eyebrow={mode === "live" ? "04 / Real-money desk" : "03 / Simulation desk"}
        title={mode === "live" ? "Live Trading" : "Paper Trading"}
        description={mode === "live" ? "Real venue balances, reconciled positions, and explicit risk controls." : "Live public books, simulated execution, and independent event budgets."}
      />
      {mode === "live" ? <div className="live-ribbon">LIVE MONEY · ORDERS CAN REACH VENUES</div> : <div className="paper-ribbon">PAPER · SIMULATED EXECUTION</div>}
      <div className="metrics-grid">
        <Metric label="Active sessions" value={String(active.length)} detail={`${workers.data?.length ?? 0} total records`} />
        <Metric label={mode === "live" ? "Venue funds" : "Paper allocation"} value={money(mode === "live" ? liveBalances : total)} detail={mode === "live" ? `${money(total)} allocated across events` : "Sum of independent budgets"} tone={mode === "live" ? "risk" : "positive"} />
        <Metric label="Open baskets" value={String(active.reduce((sum, row) => sum + Number((row.state.positions as unknown[])?.length ?? 0), 0))} detail="Across active events" />
        <Metric label="Stream health" value={active.every((row) => !row.pause_reason) ? "Nominal" : "Attention"} detail="Fresh books required for entry" />
      </div>
      <section className="panel chart-panel">
        <MarketChart
          title="Aggregate basket edge"
          yTitle="Edge per share"
          traces={[
            { x: [1, 2, 3, 4, 5, 6], y: [0, 0, 0, 0, 0, 0], type: "scatter", mode: "lines", name: "Awaiting live evaluations", line: { color: mode === "live" ? "#a23b38" : "#0d684c", width: 2 } },
          ]}
        />
      </section>
      {workers.data?.length ? (
        <section className="panel table-panel">
          <div className="panel-title"><div><p className="eyebrow">Runtime supervisor</p><h2>Event sessions</h2></div><span>{workers.data.length} records</span></div>
          <div className="data-table">
            <div className="data-row data-head"><span>Event</span><span>Budget</span><span>State</span><span>Heartbeat</span><span>Exposure / PnL</span><span /></div>
            {workers.data.map((worker) => (
              <div className="data-row" key={worker.id}>
                <span><b>{worker.event_name}</b><small>{worker.id.slice(0, 8)}</small></span>
                <span className="mono">{money(worker.budget)}</span>
                <span><StatusBadge value={worker.status} /></span>
                <span>{age(worker.heartbeat_at)}</span>
                <span className="mono">{String(worker.state.realized_pnl ?? "$0.00")}</span>
                <span className="row-actions">
                  <Link href={`/events/${worker.event_id}`}><SquareArrowOutUpRight size={15} /></Link>
                  {["starting", "running"].includes(worker.status) ? <button onClick={() => stop.mutate(worker.id)}><Pause size={15} /></button> : null}
                </span>
              </div>
            ))}
          </div>
        </section>
      ) : (
        <EmptyState title={`No ${mode} sessions`}>Start this mode from My Markets after approving an event.</EmptyState>
      )}
    </>
  );
}
