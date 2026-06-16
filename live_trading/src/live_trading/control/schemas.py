from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class OutcomeMapping(BaseModel):
    name: str
    kalshi_ticker: str
    polymarket_us_slug: str
    polymarket_side: Literal["long", "short"] = "long"
    kalshi_title: str = ""
    polymarket_title: str = ""
    kalshi_rules: str | None = None
    polymarket_rules: str | None = None
    polymarket_contract_address: str | None = None
    polymarket_yes_token_id: str | None = None


class RankingBreakdown(BaseModel):
    historical_suitability: float = 50
    annual_profit_percentile: float = 50
    pmxt_profit_percentile: float = 50
    executable_net_edge: float | None = None
    fillable_depth: float | None = None
    freshness_score: float = 0
    stability_score: float = 0
    mapping_confidence: float = 0
    total_score: float = 0
    evidence_label: str = "Historical prior unavailable"
    expected_deployable_profit: float = 0
    executable_profit: float = 0
    selected_size: float = 0
    completion_probability: float = 0
    historical_multiplier: float = 1
    historical_evidence_quality: str = "none"
    historical_sample_size: int = 0
    event_state: str = "unknown"
    max_slippage_per_share: float = 0
    ranking_components: dict[str, float] = Field(default_factory=dict)
    size_curve: list[dict[str, Any]] = Field(default_factory=list)
    exclusion_reasons: list[str] = Field(default_factory=list)


class Candidate(BaseModel):
    id: str
    name: str
    description: str | None = None
    category: str | None = None
    status: Literal["candidate", "needs_review", "approved"] = "candidate"
    mappings: list[OutcomeMapping]
    exhaustive: bool = False
    deterministic_checks: dict[str, bool] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    llm_status: Literal["pending", "passed", "failed", "unavailable"] = "pending"
    llm_confidence: float | None = None
    llm_reasoning: str | None = None
    ranking: RankingBreakdown = Field(default_factory=RankingBreakdown)
    close_time: datetime | None = None
    updated_at: datetime


class ScanRequest(BaseModel):
    query: str = ""
    categories: list[str] = Field(default_factory=list)
    max_markets: int = Field(default=250, ge=10, le=1000)
    lookback_days: int = Field(default=7, ge=1, le=30)


class ScanJob(BaseModel):
    id: str
    status: Literal["queued", "refreshing", "matching", "reviewing", "complete", "failed"]
    progress: float = 0
    message: str = ""
    candidate_count: int = 0
    errors: list[str] = Field(default_factory=list)
    started_at: datetime
    completed_at: datetime | None = None


class MarketSuggestion(BaseModel):
    id: str
    name: str
    category: str | None = None
    close_time: datetime | None = None
    outcome_count: int
    mapping_confidence: float
    kalshi_outcomes: list[str] = Field(default_factory=list)
    polymarket_outcomes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ApprovalRequest(BaseModel):
    exhaustive: bool
    settlement_reviewed: bool


class StrategySettings(BaseModel):
    preset: Literal["conservative", "balanced", "aggressive", "custom"] = "balanced"
    entry_threshold: float = Field(default=0.98, gt=0, le=1)
    slippage_buffer: float = Field(default=0.005, ge=0, le=0.2)
    trade_size: int = Field(default=100, ge=1)
    depth_haircut: float = Field(default=0.7, gt=0, le=1)
    staleness_ms: int = Field(default=2000, ge=100)
    min_leg_bid: float = Field(default=0.02, ge=0, le=1)
    max_leg_bid: float = Field(default=0.98, ge=0, le=1)
    min_non_widening_ticks: int = Field(default=2, ge=0)
    retry_seconds: float = Field(default=2, ge=0)
    max_unhedged_loss_pct: float = Field(default=0.05, ge=0, le=1)
    exit_margin: float = Field(default=0.01, ge=0)


class ModeConfiguration(BaseModel):
    event_id: str
    mode: Literal["paper", "live"]
    budget: float = Field(gt=0)
    strategy: StrategySettings = Field(default_factory=StrategySettings)


class LiveActivationRequest(ModeConfiguration):
    confirmation: str


class WorkerState(BaseModel):
    id: str
    event_id: str
    event_name: str
    mode: Literal["paper", "live"]
    budget: float
    status: Literal["starting", "running", "paused", "stopped", "failed"]
    pid: int | None = None
    started_at: datetime | None = None
    heartbeat_at: datetime | None = None
    pause_reason: str | None = None
    state: dict[str, Any] = Field(default_factory=dict)


class BacktestRequest(BaseModel):
    event_id: str
    starting_cash: float = Field(default=1000, gt=0)
    start_date: str | None = None
    end_date: str | None = None


class BacktestJob(BaseModel):
    id: str
    event_id: str
    event_name: str
    status: Literal["queued", "validating", "running", "complete", "unavailable", "failed"]
    progress: float = 0
    starting_cash: float = 1000
    unavailable_reasons: list[str] = Field(default_factory=list)
    result: dict[str, Any] | None = None
    created_at: datetime
    completed_at: datetime | None = None


class SettingsStatus(BaseModel):
    credentials: dict[str, bool]
    connections: dict[str, dict[str, Any]]
    openai_available: bool
    storage: dict[str, str]
    workers: list[WorkerState]
    emergency_stop: bool
