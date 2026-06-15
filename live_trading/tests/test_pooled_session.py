from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import yaml

from live_trading.config import Settings
from live_trading.market_data.cache import CacheUpdate
from live_trading.models import BookState, PriceLevel
from live_trading.pooled_session import PooledEventSession


def _book(venue: str, key: str, sequence: int) -> BookState:
    return BookState(
        venue=venue,  # type: ignore[arg-type]
        market_key=key,
        yes_bid=Decimal("0.19"),
        yes_ask=Decimal("0.20"),
        no_bid=Decimal("0.80"),
        no_ask=Decimal("0.81"),
        raw_yes_bids=(PriceLevel(Decimal("0.19"), Decimal("500")),),
        raw_yes_asks=(PriceLevel(Decimal("0.20"), Decimal("500")),),
        received_ts=datetime.now(timezone.utc),
        sequence=sequence,
        state="snapshot",
    )


def test_pooled_paper_session_consumes_shared_updates(tmp_path, monkeypatch) -> None:
    async def run() -> None:
        monkeypatch.setenv("LIVE_TRADING_DATA_DIR", str(tmp_path / "data"))
        manifest = tmp_path / "event.yaml"
        manifest.write_text(
            yaml.safe_dump(
                {
                    "event": {
                        "name": "Synthetic Event",
                        "outcomes": [
                            {
                                "name": "A",
                                "kalshi_ticker": "K-A",
                                "polymarket_us_slug": "P-A",
                            },
                            {
                                "name": "B",
                                "kalshi_ticker": "K-B",
                                "polymarket_us_slug": "P-B",
                            },
                        ],
                    },
                    "review": {
                        "approved": True,
                        "exhaustive": True,
                        "settlement_reviewed": True,
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        session = PooledEventSession(
            session_id="synthetic:paper",
            mode="paper",
            manifest_path=manifest,
            capital=Decimal("100"),
            strategy={"min_non_widening_ticks": 0, "trade_size": 10},
            settings=Settings.from_env(),
            data_root=tmp_path / "data",
        )
        markets = await session.start()
        assert len(markets) == 4
        for sequence, (venue, key) in enumerate(sorted(markets), start=1):
            await session.on_market_update(
                CacheUpdate(_book(venue, key, sequence), valid=True)
            )
        await asyncio.sleep(0.25)

        assert session.latest_evaluation is not None
        assert session.latest_evaluation.edge_per_share > 0
        assert len((await session.store.snapshot())) == 4
        await session.close()

    asyncio.run(run())
