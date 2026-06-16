"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Check, Plus, RefreshCw, Search, Sparkles, Trash2 } from "lucide-react";
import { api, money, pct } from "@/lib/api";
import type { Candidate, MarketSuggestion, ScanJob, SelectedMarket } from "@/lib/types";
import { EmptyState, PageHead, Progress, StatusBadge } from "@/components/ui";

export default function DiscoverPage() {
  const client = useQueryClient();
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [activeScanName, setActiveScanName] = useState<string | null>(null);
  const [basket, setBasket] = useState<SelectedMarket[]>(() => readDiscoveryBasket());
  const [selected, setSelected] = useState<Candidate | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    window.localStorage.setItem("discovery-basket-v1", JSON.stringify(basket));
  }, [basket]);

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
      const active = queryState.state.data?.some((row) => ["queued", "refreshing", "matching", "reviewing"].includes(row.status));
      return active ? 1000 : false;
    },
  });
  const activeScans = (scans.data ?? []).filter((row) => ["queued", "refreshing", "matching", "reviewing"].includes(row.status));
  const currentScan = activeScans[0] ?? scans.data?.[0];
  const scanActive = activeScans.length > 0;
  const candidates = useQuery({
    queryKey: ["candidates"],
    queryFn: () => api<Candidate[]>("/candidates"),
    staleTime: 1000,
    refetchInterval: scanActive ? 1000 : false,
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
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["scans"] });
      client.invalidateQueries({ queryKey: ["candidates"] });
    },
  });
  const scanBasket = useMutation({
    mutationFn: async (items: SelectedMarket[]) => {
      await Promise.all(items.map((item) => startScan(item.name)));
      return items.length;
    },
    onMutate: (items) => setActiveScanName(`${items.length} selected event${items.length === 1 ? "" : "s"}`),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["scans"] });
      client.invalidateQueries({ queryKey: ["candidates"] });
    },
  });
  const filtered = useMemo(() => candidates.data ?? [], [candidates.data]);

  useEffect(() => {
    if (currentScan?.status === "complete" || currentScan?.status === "failed") {
      client.invalidateQueries({ queryKey: ["candidates"] });
    }
  }, [client, currentScan?.status]);

  function scanForReview(name: string) {
    setActiveScanName(name);
    scan.mutate(name);
  }

  function addToBasket(item: MarketSuggestion) {
    setBasket((current) => {
      if (current.some((row) => row.id === item.id)) return current;
      return [{ ...item, added_at: new Date().toISOString() }, ...current];
    });
  }

  function removeFromBasket(id: string) {
    setBasket((current) => current.filter((item) => item.id !== id));
  }

  function clearBasket() {
    setBasket([]);
  }

  return (
    <>
      <PageHead
        eyebrow="01 / Market intake"
        title="Search events on Kalshi and Polymarket"
        actions={
          <button className="button primary" onClick={() => scanBasket.mutate(basket)} disabled={scanBasket.isPending || scan.isPending || basket.length === 0}>
            <Sparkles size={16} /> {scanBasket.isPending ? "Scanning..." : "Scan basket"}
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
        <span>{basket.length} selected</span>
      </section>
      {debouncedQuery.length >= 2 ? (
        <section className="suggestion-panel">
          <div className="suggestion-title">
            <div>
              <p className="eyebrow">Typeahead</p>
              <h2>Matching events</h2>
            </div>
            <span>{suggestions.isFetching ? "Searching..." : `${suggestions.data?.length ?? 0} suggestions`}</span>
          </div>
          {suggestions.data?.length ? (
            <div className="suggestion-list">
              {suggestions.data.map((item) => (
                <SuggestionRow
                  key={item.id}
                  item={item}
                  selected={basket.some((row) => row.id === item.id)}
                  onAdd={() => addToBasket(item)}
                  onRemove={() => removeFromBasket(item.id)}
                />
              ))}
            </div>
          ) : (
            <p className="suggestion-empty">
              {suggestions.isFetching ? "Searching recent tradable catalogs..." : "No shared Kalshi/Polymarket US event suggestions matched this text."}
            </p>
          )}
        </section>
      ) : null}
      <section className="basket-panel">
        <div className="basket-title">
          <div>
            <p className="eyebrow">Selected events</p>
            <h2>Trading basket</h2>
          </div>
          <div className="basket-actions">
            <button className="button ghost compact" onClick={clearBasket} disabled={!basket.length}>Clear</button>
            <button className="button primary compact" onClick={() => scanBasket.mutate(basket)} disabled={!basket.length || scanBasket.isPending || scan.isPending}>
              <Sparkles size={14} /> {scanBasket.isPending ? "Scanning..." : "Prepare review"}
            </button>
          </div>
        </div>
        {basket.length ? (
          <div className="basket-list">
            {basket.map((item) => (
                <div
                  className="basket-row"
                  key={item.id}
                >
                  <span>
                    <b>{item.name}</b>
                    <small>
                      {item.category ?? "Uncategorized"} · {item.outcome_count || "—"} markets · {(item.mapping_confidence * 100).toFixed(0)}% match · {item.source}
                    </small>
                  </span>
                  <span className="suggestion-books">
                    {item.venues.join(" + ") || "Venue match pending"} · Kalshi: {item.kalshi_outcomes.slice(0, 2).join(" / ") || "pending"} · Polymarket: {item.polymarket_outcomes.slice(0, 2).join(" / ") || "pending"}
                  </span>
                  <button className="button compact" onClick={() => scanForReview(item.name)} disabled={scan.isPending || scanBasket.isPending}>
                    <Sparkles size={14} /> Scan
                  </button>
                  <button className="icon-button" onClick={() => removeFromBasket(item.id)} aria-label={`Remove ${item.name}`}>
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <p className="suggestion-empty">Add events from search results. Nothing is scanned or refreshed until you choose Prepare review.</p>
          )}
      </section>
      {currentScan ? (
        <section className="scan-strip">
          <div>
            <RefreshCw size={15} className={["refreshing", "matching", "reviewing"].includes(currentScan.status) ? "spin" : ""} />
            <strong>{scanActive && activeScanName ? `Preparing ${activeScanName}` : currentScan.message}</strong>
            <StatusBadge value={currentScan.status} />
          </div>
          <Progress value={currentScan.progress} />
          <small>{currentScan.candidate_count} review-ready candidates · {activeScans.length || 1} scan{(activeScans.length || 1) === 1 ? "" : "s"}</small>
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
        <EmptyState title="No review-ready events yet">
          Search for an event, then choose Scan for review. Approved events appear in My Markets.
        </EmptyState>
      )}
      {selected ? <ReviewDialog candidate={selected} onClose={() => setSelected(null)} /> : null}
    </>
  );
}

function SuggestionRow({
  item,
  selected,
  onAdd,
  onRemove,
}: {
  item: MarketSuggestion;
  selected: boolean;
  onAdd: () => void;
  onRemove: () => void;
}) {
  return (
    <div className="suggestion-row">
      <span>
        <b>{item.name}</b>
        <small>
          {item.category ?? "Uncategorized"} · {item.outcome_count || "—"} markets · {(item.mapping_confidence * 100).toFixed(0)}% match · {item.source}
        </small>
      </span>
      <span className="suggestion-books">
        {item.venues.join(" + ") || "Venue match pending"} · Kalshi: {item.kalshi_outcomes.slice(0, 2).join(" / ") || "pending"} · Polymarket: {item.polymarket_outcomes.slice(0, 2).join(" / ") || "pending"}
      </span>
      <button className={selected ? "button compact ghost" : "button compact"} onClick={selected ? onRemove : onAdd}>
        {selected ? <Check size={14} /> : <Plus size={14} />} {selected ? "Added" : "Add"}
      </button>
    </div>
  );
}

function readDiscoveryBasket(): SelectedMarket[] {
  if (typeof window === "undefined") return [];
  try {
    const parsed = JSON.parse(window.localStorage.getItem("discovery-basket-v1") || "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function startScan(scanQuery: string) {
  return api<ScanJob>("/scans", {
    method: "POST",
    body: JSON.stringify({
      query: scanQuery,
      categories: [],
      max_markets: 250,
      lookback_days: 7,
    }),
  });
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
