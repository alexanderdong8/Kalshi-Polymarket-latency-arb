from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from .models import ArbOpportunity, BookState, MatchedMarket, Venue


def fmt_price(value: Decimal | None) -> str:
    return "-" if value is None else f"{value:.4f}"


def fmt_edge(value: Decimal | None) -> str:
    return "-" if value is None else f"{value * Decimal('100'):.2f}c"


class Dashboard:
    def __init__(self, stale_after_seconds: Decimal) -> None:
        self.console = Console()
        self.stale_after_seconds = stale_after_seconds

    def render(
        self,
        matches: list[MatchedMarket],
        books: dict[tuple[Venue, str], BookState],
        opportunities: list[ArbOpportunity],
    ) -> Group:
        return Group(
            self._summary(matches, books, opportunities),
            self._opportunities(opportunities[:12]),
            self._matched_markets(matches[:25], books),
        )

    def live(self, refresh_per_second: float = 4.0) -> Live:
        return Live(console=self.console, refresh_per_second=refresh_per_second, screen=False)

    def _summary(
        self,
        matches: list[MatchedMarket],
        books: dict[tuple[Venue, str], BookState],
        opportunities: list[ArbOpportunity],
    ) -> Panel:
        now = datetime.now(timezone.utc)
        fresh_books = sum(not book.is_stale(self.stale_after_seconds, now) for book in books.values())
        best_net = opportunities[0].net_edge_per_contract if opportunities else None
        text = (
            f"matches={len(matches)}  books={len(books)}  fresh_books={fresh_books}  "
            f"opportunities={len(opportunities)}  best_net={fmt_edge(best_net)}  "
            f"utc={now.isoformat(timespec='seconds')}"
        )
        return Panel(text, title="Live Matched-Market Scanner", expand=True)

    def _opportunities(self, opportunities: Iterable[ArbOpportunity]) -> Table:
        table = Table(title="Best Current Opportunities")
        table.add_column("Match")
        table.add_column("Direction")
        table.add_column("YES")
        table.add_column("NO")
        table.add_column("Cost")
        table.add_column("Gross")
        table.add_column("Net")
        table.add_column("Depth")
        table.add_column("Review")
        for opp in opportunities:
            table.add_row(
                opp.match_id[:36],
                opp.direction,
                f"{opp.yes_venue} {fmt_price(opp.yes_ask)}",
                f"{opp.no_venue} {fmt_price(opp.no_ask)}",
                fmt_price(opp.entry_cost),
                fmt_edge(opp.gross_edge_per_contract),
                fmt_edge(opp.net_edge_per_contract),
                "-" if opp.depth_limited_contracts is None else f"{opp.depth_limited_contracts:.2f}",
                "yes" if opp.warnings else "",
            )
        return table

    def _matched_markets(
        self,
        matches: list[MatchedMarket],
        books: dict[tuple[Venue, str], BookState],
    ) -> Table:
        table = Table(title="Matched Markets")
        table.add_column("Confidence")
        table.add_column("Kalshi")
        table.add_column("K YES/NO ask")
        table.add_column("Polymarket US")
        table.add_column("P YES/NO ask")
        table.add_column("Status")
        now = datetime.now(timezone.utc)
        for match in matches:
            kalshi = books.get(("kalshi", match.kalshi.stream_key))
            poly = books.get(("polymarket_us", match.polymarket_us.stream_key))
            status = []
            if match.warnings:
                status.append("review")
            if kalshi and kalshi.is_stale(self.stale_after_seconds, now):
                status.append("kalshi stale")
            if poly and poly.is_stale(self.stale_after_seconds, now):
                status.append("poly stale")
            table.add_row(
                f"{match.confidence:.3f}",
                match.kalshi.title[:42],
                f"{fmt_price(kalshi.yes_ask if kalshi else None)} / {fmt_price(kalshi.no_ask if kalshi else None)}",
                match.polymarket_us.title[:42],
                f"{fmt_price(poly.yes_ask if poly else None)} / {fmt_price(poly.no_ask if poly else None)}",
                ", ".join(status),
            )
        return table

