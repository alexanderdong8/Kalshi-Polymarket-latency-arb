# Discover Recent Search Design

## Problem

The Discover page looked like a market search UI, but it only filtered stored
scanner candidates. If no completed scan had already produced candidates, typing
could not surface anything. The explicit scan also refreshed broad venue
catalogs before showing progress, so the UI could sit on "refreshing complete
venue catalogs" for too long.

## Decision

Discover now has two paths:

- Typeahead suggestions query recent cached venue catalogs and return event-level
  Kalshi/Polymarket US matches while the user types.
- Scan Markets runs the deeper matcher, LLM review, and L2 ranking over tradable
  venue records from the last seven days by default.

"Past seven days" means tradable events whose venue open/created/start metadata
falls inside the lookback window. Completed historical events remain a backtest
concern, not a live Discover scan concern.

## Consequences

- The first typeahead request may perform one quick recent-catalog refresh if no
  fresh cache exists.
- Search suggestions are not approval records. A user still runs a scan and then
  reviews the LLM/deterministic result before approving an event.
- Full catalog discovery can be added later as an explicit advanced scan mode,
  but the default local workflow stays fast and recent.
