from decimal import Decimal

import pytest

from live_trading.strategy.manifest import ManifestError, load_event_manifest


def test_manifest_requires_review_and_complete_multi_outcome_mapping(tmp_path):
    path = tmp_path / "event.yaml"
    path.write_text(
        """
event:
  name: Test Event
  outcomes:
    - name: A
      kalshi_ticker: K-A
      polymarket_us_slug: p-a
    - name: B
      kalshi_ticker: K-B
      polymarket_us_slug: p-b
review:
  approved: false
  exhaustive: true
  settlement_reviewed: true
""",
        encoding="utf-8",
    )
    manifest = load_event_manifest(path)
    assert len(manifest.event.outcomes) == 2
    with pytest.raises(ManifestError, match="approved"):
        manifest.require_tradeable()


def test_manifest_rejects_duplicate_outcome_identifiers(tmp_path):
    path = tmp_path / "event.yaml"
    path.write_text(
        """
event:
  name: Test Event
  outcomes:
    - {name: A, kalshi_ticker: K-A, polymarket_us_slug: p-a}
    - {name: B, kalshi_ticker: K-A, polymarket_us_slug: p-b}
""",
        encoding="utf-8",
    )
    with pytest.raises(ManifestError, match="Duplicate Kalshi"):
        load_event_manifest(path)
