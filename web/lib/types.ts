export type Ranking = {
  historical_suitability: number;
  annual_profit_percentile: number;
  pmxt_profit_percentile: number;
  executable_net_edge: number | null;
  fillable_depth: number | null;
  freshness_score: number;
  stability_score: number;
  mapping_confidence: number;
  total_score: number;
  evidence_label: string;
  expected_deployable_profit: number;
  executable_profit: number;
  selected_size: number;
  completion_probability: number;
  historical_multiplier: number;
  historical_evidence_quality: string;
  historical_sample_size: number;
  event_state: string;
  max_slippage_per_share: number;
  ranking_components: Record<string, number>;
  size_curve: {
    requested_size: number;
    achievable_size: number;
    net_edge_per_share: number;
    executable_profit: number;
    max_slippage_per_share: number;
    eligible: boolean;
  }[];
  exclusion_reasons: string[];
};

export type Mapping = {
  name: string;
  kalshi_ticker: string;
  polymarket_us_slug: string;
  polymarket_side: "long" | "short";
  kalshi_title: string;
  polymarket_title: string;
  kalshi_rules?: string | null;
  polymarket_rules?: string | null;
};

export type Candidate = {
  id: string;
  name: string;
  description?: string | null;
  category?: string | null;
  status: string;
  mappings: Mapping[];
  exhaustive: boolean;
  deterministic_checks: Record<string, boolean>;
  warnings: string[];
  llm_status: string;
  llm_confidence?: number | null;
  llm_reasoning?: string | null;
  ranking: Ranking;
  close_time?: string | null;
  updated_at: string;
};

export type MarketEvent = Candidate & {
  slug: string;
  manifest_path: string;
  approval_version: string;
  approved_at: string;
  active_modes: string[];
  workers?: Worker[];
  configurations?: unknown[];
  offline_intervals?: { started_at: string; ended_at: string | null }[];
};

export type Worker = {
  id: string;
  event_id: string;
  event_name: string;
  mode: "paper" | "live";
  budget: number;
  status: string;
  pid?: number | null;
  started_at?: string | null;
  heartbeat_at?: string | null;
  pause_reason?: string | null;
  state: Record<string, unknown>;
};

export type ScanJob = {
  id: string;
  status: string;
  progress: number;
  message: string;
  candidate_count: number;
  errors: string[];
  started_at: string;
  completed_at?: string | null;
};

export type BacktestJob = {
  id: string;
  event_id: string;
  event_name: string;
  status: string;
  progress: number;
  starting_cash: number;
  unavailable_reasons: string[];
  result?: { results?: Record<string, string>[]; coverage?: unknown; venue_split?: string } | null;
  created_at: string;
};

export type Strategy = {
  preset: "conservative" | "balanced" | "aggressive" | "custom";
  entry_threshold: number;
  slippage_buffer: number;
  trade_size: number;
  depth_haircut: number;
  staleness_ms: number;
  min_leg_bid: number;
  max_leg_bid: number;
  min_non_widening_ticks: number;
  retry_seconds: number;
  max_unhedged_loss_pct: number;
  exit_margin: number;
};

export const balancedStrategy: Strategy = {
  preset: "balanced",
  entry_threshold: 0.98,
  slippage_buffer: 0.005,
  trade_size: 100,
  depth_haircut: 0.7,
  staleness_ms: 2000,
  min_leg_bid: 0.02,
  max_leg_bid: 0.98,
  min_non_widening_ticks: 2,
  retry_seconds: 2,
  max_unhedged_loss_pct: 0.05,
  exit_margin: 0.01,
};
