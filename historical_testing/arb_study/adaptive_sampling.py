from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class SamplingWindow:
    label: str
    start: datetime
    end: datetime
    interval_minutes: int

    def as_dict(self) -> dict[str, str | int]:
        return {
            **asdict(self),
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
        }


def adaptive_sampling_windows(
    available_start: datetime,
    resolution: datetime,
    *,
    is_sports: bool,
    event_start: datetime | None = None,
) -> list[SamplingWindow]:
    """Describe the historical-price requests without pretending all periods move equally fast."""
    start = _utc(available_start)
    end = _utc(resolution)
    if start >= end:
        return []
    if is_sports:
        if event_start is None:
            final_day = max(start, end - timedelta(hours=24))
            return _compact(
                [
                    SamplingWindow("sports_pregame_slow", start, final_day, 60),
                    SamplingWindow("sports_event_start_unavailable_final_24h", final_day, end, 5),
                ]
            )
        live_start = _utc(event_start)
        live_start = min(max(live_start, start), end)
        final_day = max(start, live_start - timedelta(hours=24))
        return _compact(
            [
                SamplingWindow("sports_pregame_slow", start, final_day, 60),
                SamplingWindow("sports_pregame_final_24h", final_day, live_start, 5),
                SamplingWindow("sports_in_play", live_start, end, 1),
            ]
        )

    final_day = max(start, end - timedelta(hours=24))
    final_month = max(start, end - timedelta(days=30))
    return _compact(
        [
            SamplingWindow("lifecycle_more_than_30d", start, final_month, 1440),
            SamplingWindow("lifecycle_30d_to_24h", final_month, final_day, 60),
            SamplingWindow("lifecycle_final_24h", final_day, end, 5),
        ]
    )


def _compact(windows: list[SamplingWindow]) -> list[SamplingWindow]:
    return [window for window in windows if window.start < window.end]


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
