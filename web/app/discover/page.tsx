"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, RefreshCw, Search, Sparkles } from "lucide-react";
import { api, money, pct } from "@/lib/api";
import type { Candidate, MarketSuggestion, ScanJob } from "@/lib/types";
import { EmptyState, PageHead, Progress, StatusBadge } from "@/components/ui";

export default function DiscoverPage() {
  const client = useQueryClient();
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [selected, setSelected] = useState<Candidate | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [query]);

  const candidates = useQuery({
    queryKey: ["candidates", debouncedQuery],
    queryFn: () =>
      api<Candidate[]>(
        `/candidates${debouncedQuery ? `?query=${encodeURIComponent(debouncedQuery)}` : ""}`,
      ),
    staleTime: 1000,
  });
  const suggestions = useQuery({
    queryKey: ["market-suggestions", debouncedQuery],
    queryFn: () =>
      api<MarketSuggestion[]>(
        `/market-suggestions?query=${encodeURIComponent(debouncedQuery)}&lookback_days=7&limit=8`,
      ),
    enabled: debouncedQuery.length >= 2,
    staleTime: 30_000,
  });
  const scans = useQuery({
    queryKey: ["scans"],
    queryFn: () => api<ScanJob[]>("/scans"),
    refetchInterval: (queryState) => {
      const current = queryState.state.data?.[0];
      return current && ["queued", "refreshing", "matching", "reviewing"].includes(current.status) ? 1000 : false;
    },
  });
  const scan = useMutation({
    mutationFn: (scanQuery?: string) =>
      api<ScanJob>("/scans", {
        method: "POST",
        body: JSON.stringify({
          query: scanQuery ?? query,
          categories: [],
          max_markets: 250,
          lookback_days: 7,
        }),
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["scans"] }),
  });
  const filtered = useMemo(() => candidates.data ?? [], [candidates.data]);
  const currentScan = scans.data?.[0];

  return (
    <>
      <PageHead
        eyebrow="01 / Market intake"
        title="Find complete events, not loose contracts."
        description="Refresh both venues, match every outcome, inspect settlement equivalence, then approve the event you actually intend to trade."
        actions={
          <button className="button primary" onClick={() => scan.mutate(query)} disabled={scan.isPending}>
            <Sparkles size={16} /> {scan.isPending ? "Starting..." : "Scan markets"}
          </button>
        }
      />
      <section className="search-panel">
        <Search size={19} />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search event, category, Kalshi ticker, or Polymarket slug"
          aria-label="Search markets"
        />
        <span>{filtered.length} candidates</span>
      </section>
      {debouncedQuery.length >= 2 ? (
        <section className="suggestion-panel">
          <div className="suggestion-title">
            <div>
              <p className="eyebrow">Typeahead</p>
              <h2>Shared tradable events from the last 7 days</h2>
            </div>
            <span>{suggestions.isFetching ? "Searching..." : `${suggestions.data?.length ?? 0} suggestions`}</span>
          </div>
          {suggestions.data?.length ? (
            <div className="suggestion-list">
              {suggestions.data.map((item) => (
                <button
                  className="suggestion-row"
                  key={item.id}
                  onClick={() => {
                    setQuery(item.name);
                    scan.mutate(item.name);
                  }}
                >
                  <span>
                    <b>{item.name}</b>
                    <small>
                      {item.category ?? "Uncategorized"} · {item.outcome_count} mapped outcomes · {(item.mapping_confidence * 100).toFixed(0)}% match
                    </small>
                  </span>
                  <span className="suggestion-books">
                    Kalshi: {item.kalshi_outcomes.join(" / ")} · Polymarket: {item.polymarket_outcomes.join(" / ")}
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <p className="suggestion-empty">
              {suggestions.isFetching ? "Searching recent tradable catalogs..." : "No shared Kalshi/Polymarket US event suggestions matched this text."}
            </p>
          )}
        </section>
      ) : null}
      {currentScan ? (
        <section className="scan-strip">
          <div>
            <RefreshCw size={15} className={["refreshing", "matching", "reviewing"].includes(currentScan.status) ? "spin" : ""} />
            <strong>{currentScan.message}</strong>
            <StatusBadge value={currentScan.status} />
          </div>
          <Progress value={currentScan.progress} />
          <small>{currentScan.candidate_count} candidates · recent tradable catalogs, 7-day lookback</small>
        </section>
      ) : null}
      {filtered.length ? (
        <div className="candidate-grid">
          {filtered.map((candidate, index) => (
            <article className="candidate-card reveal" style={{ animationDelay: `${index * 45}ms` }} key={candidate.id}>
              <div className="candidate-topline">
                <span>{candidate.category ?? "Uncategorized"}</span>
                <StatusBadge value={candidate.llm_status} />
              </div>
              <h2>{candidate.name}</h2>
              <p>{candidate.description || "Settlement details available in event review."}</p>
              <div className="score-grid">
                <span><small>Expected profit</small><b>{money(candidate.ranking.expected_deployable_profit)}</b></span>
                <span><small>Executable now</small><b>{money(candidate.ranking.executable_profit)}</b></span>
                <span><small>Completion estimate</small><b>{pct(candidate.ranking.completion_probability)}</b></span>
                <span><small>Deployable size</small><b>{candidate.ranking.selected_size || "—"}</b></span>
              </div>
              <p className="evidence-line">
                {candidate.ranking.event_state.replaceAll("_", " ")} · {candidate.ranking.evidence_label}
              </p>
              <div className="candidate-footer">
                <span className={candidate.exhaustive ? "coverage good" : "coverage"}>
                  {candidate.exhaustive ? "Complete coverage" : "Coverage warning"}
                </span>
                <button className="text-button" onClick={() => setSelected(candidate)}>
                  Review event <ArrowRight size={14} />
                </button>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <EmptyState title="No candidate events yet">
          Run an explicit scan to refresh the complete Kalshi and Polymarket US catalogs. The scanner will not approve anything on its own.
        </EmptyState>
      )}
      {selected ? <ReviewDialog candidate={selected} onClose={() => setSelected(null)} /> : null}
    </>
  );
}

function ReviewDialog({ candidate, onClose }: { candidate: Candidate; onClose: () => void }) {
  const client = useQueryClient();
  const [exhaustive, setExhaustive] = useState(false);
  const [settlement, setSettlement] = useState(false);
  const approve = useMutation({
    mutationFn: () =>
      api(`/candidates/${candidate.id}/approve`, {
        method: "POST",
        body: JSON.stringify({ exhaustive, settlement_reviewed: settlement }),
      }),
    onSuccess: () => {
      client.invalidateQueries();
      onClose();
    },
  });
  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <section className="review-sheet" onMouseDown={(event) => event.stopPropagation()}>
        <header>
          <div><p className="eyebrow">Event review</p><h2>{candidate.name}</h2></div>
          <StatusBadge value={candidate.llm_status} />
        </header>
        <div className="review-summary">
          <div><small>LLM confidence</small><strong>{pct(candidate.llm_confidence)}</strong></div>
          <div><small>Complete outcomes</small><strong>{candidate.exhaustive ? "Yes" : "No"}</strong></div>
          <div><small>Expected deployable profit</small><strong>{money(candidate.ranking.expected_deployable_profit)}</strong></div>
          <div><small>Selected size</small><strong>{candidate.ranking.selected_size || "Unavailable"}</strong></div>
          <div><small>Completion estimate</small><strong>{pct(candidate.ranking.completion_probability)}</strong></div>
          <div><small>Current net edge</small><strong>{pct(candidate.ranking.executable_net_edge)}</strong></div>
        </div>
        <div className="reasoning">
          <b>Ranking evidence</b>
          <p>{candidate.ranking.evidence_label}. Current event state: {candidate.ranking.event_state.replaceAll("_", " ")}. Historical multiplier: {candidate.ranking.historical_multiplier.toFixed(3)}.</p>
          {candidate.ranking.exclusion_reasons.map((reason) => <p key={reason}>{reason}</p>)}
        </div>
        <div className="reasoning"><b>Settlement review</b><p>{candidate.llm_reasoning ?? "No LLM judgment is available. Approval remains blocked."}</p></div>
        <div className="mapping-table">
          <div className="mapping-row mapping-head"><span>Outcome</span><span>Kalshi</span><span>Polymarket US</span></div>
          {candidate.mappings.map((mapping) => (
            <div className="mapping-row" key={mapping.name}>
              <strong>{mapping.name}</strong>
              <span><b>{mapping.kalshi_ticker}</b><small>{mapping.kalshi_title}</small></span>
              <span><b>{mapping.polymarket_us_slug} · {mapping.polymarket_side}</b><small>{mapping.polymarket_title}</small></span>
            </div>
          ))}
        </div>
        <div className="checks">
          {Object.entries(candidate.deterministic_checks).map(([label, passed]) => (
            <span className={passed ? "check pass" : "check fail"} key={label}>{passed ? "✓" : "×"} {label.replaceAll("_", " ")}</span>
          ))}
        </div>
        {candidate.warnings.length ? <div className="warning-box">{candidate.warnings.map((warning) => <p key={warning}>{warning}</p>)}</div> : null}
        <label className="review-check"><input type="checkbox" checked={exhaustive} onChange={(event) => setExhaustive(event.target.checked)} /> I reviewed every outcome and confirm the set is mutually exclusive and exhaustive.</label>
        <label className="review-check"><input type="checkbox" checked={settlement} onChange={(event) => setSettlement(event.target.checked)} /> I reviewed the settlement rules, deadlines, cancellation treatment, and event scope.</label>
        {approve.error ? <p className="form-error">{approve.error.message}</p> : null}
        <footer>
          <button className="button ghost" onClick={onClose}>Close</button>
          <button className="button primary" disabled={!exhaustive || !settlement || candidate.llm_status !== "passed" || approve.isPending} onClick={() => approve.mutate()}>
            Approve and add to My Markets
          </button>
        </footer>
      </section>
    </div>
  );
}
