"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, money } from "@/lib/api";
import { canActivateLive } from "@/lib/live-safety";
import { balancedStrategy, type MarketEvent } from "@/lib/types";

export function ModeDialog({
  event,
  mode,
  onClose,
}: {
  event: MarketEvent;
  mode: "paper" | "live" | "backtest";
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [budget, setBudget] = useState(mode === "backtest" ? 1000 : 100);
  const [confirmation, setConfirmation] = useState("");
  const preview = useQuery({
    queryKey: ["live-preview", event.id, budget],
    queryFn: () =>
      api<{
        reconciliation: {
          kalshi_balance: string | null;
          polymarket_us_balance: string | null;
          unresolved_local_orders: unknown[];
          local_open_positions: unknown[];
          kalshi_positions: unknown[];
          polymarket_us_positions: unknown[];
        };
        warnings: string[];
        maximum_new_exposure: number;
      }>(`/events/${event.id}/live/preview?budget=${budget}`, { method: "POST" }),
    enabled: mode === "live" && budget > 0,
    retry: false,
  });
  const mutation = useMutation({
    mutationFn: async () => {
      if (mode === "backtest") {
        return api("/backtests", {
          method: "POST",
          body: JSON.stringify({ event_id: event.id, starting_cash: budget }),
        });
      }
      return api(`/events/${event.id}/${mode}/start`, {
        method: "POST",
        body: JSON.stringify({
          event_id: event.id,
          mode,
          budget,
          strategy: balancedStrategy,
          ...(mode === "live" ? { confirmation } : {}),
        }),
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries();
      onClose();
    },
  });
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section className={`modal ${mode === "live" ? "live-modal" : ""}`} onMouseDown={(e) => e.stopPropagation()}>
        <p className="eyebrow">{mode === "backtest" ? "Historical replay" : `${mode} strategy`}</p>
        <h2>{event.name}</h2>
        <p className="modal-copy">
          {mode === "live"
            ? "This can send real orders. Venue state and balances are reconciled before activation."
            : mode === "paper"
              ? "Paper fills use live public L2 books without mutating them."
              : "Replay PMXT Kalshi and international Polymarket data when complete coverage exists."}
        </p>
        <label>
          {mode === "backtest" ? "Starting bankroll" : "Independent event budget"}
          <div className="money-input"><span>$</span><input type="number" min="1" value={budget} onChange={(e) => setBudget(Number(e.target.value))} /></div>
        </label>
        {mode === "live" ? (
          <>
            <div className="live-preview">
              <div><span>Kalshi balance</span><b>{money(preview.data?.reconciliation.kalshi_balance)}</b></div>
              <div><span>Polymarket US balance</span><b>{money(preview.data?.reconciliation.polymarket_us_balance)}</b></div>
              <div><span>Maximum new exposure</span><b>{money(preview.data?.maximum_new_exposure ?? budget)}</b></div>
              <div><span>Existing venue positions</span><b>{(preview.data?.reconciliation.kalshi_positions.length ?? 0) + (preview.data?.reconciliation.polymarket_us_positions.length ?? 0)}</b></div>
              <div><span>Resting local orders</span><b>{preview.data?.reconciliation.unresolved_local_orders.length ?? 0}</b></div>
              <div><span>Approved outcomes</span><b>{event.mappings.length}</b></div>
            </div>
            {preview.error ? <p className="form-error">Live reconciliation blocked: {preview.error.message}</p> : null}
            {preview.data?.warnings.map((warning) => <p className="form-error" key={warning}>{warning}</p>)}
            <label>
              Type LIVE to confirm
              <input value={confirmation} onChange={(e) => setConfirmation(e.target.value)} placeholder="LIVE" />
            </label>
          </>
        ) : null}
        {mutation.error ? <p className="form-error">{mutation.error.message}</p> : null}
        <div className="modal-actions">
          <button className="button ghost" onClick={onClose}>Cancel</button>
          <button
            className={mode === "live" ? "button danger" : "button primary"}
            disabled={
              mutation.isPending
              || (mode === "live" && !canActivateLive(confirmation, Boolean(preview.data)))
            }
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? "Starting..." : `Start ${mode}`}
          </button>
        </div>
      </section>
    </div>
  );
}
