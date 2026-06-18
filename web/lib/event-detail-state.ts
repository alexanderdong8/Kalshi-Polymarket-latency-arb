import type { Data } from "plotly.js";
import type { RuntimeBook, RuntimeState } from "@/lib/types";

export type WindowKey = "30m" | "3h";
export type VenueKey = "kalshi" | "polymarket_us";
export type SideKey = "yes" | "no";

export type HistoryPoint = {
  ts: number;
  outcome: string;
  venue: VenueKey;
  side: SideKey;
  price: number;
};

export const WINDOW_MS: Record<WindowKey, number> = {
  "30m": 30 * 60 * 1000,
  "3h": 3 * 60 * 60 * 1000,
};

const TRACE_STYLE: Record<string, { color: string; dash?: "dash" }> = {
  "kalshi:yes": { color: "#15251e" },
  "kalshi:no": { color: "#7a817b", dash: "dash" },
  "polymarket_us:yes": { color: "#0d684c" },
  "polymarket_us:no": { color: "#5db88e", dash: "dash" },
};

export function appendHistory(current: HistoryPoint[], state: RuntimeState, now = Date.now()): HistoryPoint[] {
  const books = state.books ?? {};
  const next = [...current];
  for (const book of Object.values(books)) {
    const ts = Date.parse(book.received_ts || String(state.timestamp || ""));
    if (!Number.isFinite(ts)) continue;
    const yes = displayPrice(book, "yes");
    const no = displayPrice(book, "no");
    if (yes !== null) next.push({ ts, outcome: book.outcome, venue: book.venue, side: "yes", price: yes });
    if (no !== null) next.push({ ts, outcome: book.outcome, venue: book.venue, side: "no", price: no });
  }
  const cutoff = now - WINDOW_MS["3h"];
  return dedupePoints(next.filter((point) => point.ts >= cutoff));
}

export function buildTraces(
  history: HistoryPoint[],
  outcome: string,
  windowKey: WindowKey,
  now = Date.now(),
): Data[] {
  const cutoff = now - WINDOW_MS[windowKey];
  const visible = history.filter((point) => point.outcome === outcome && point.ts >= cutoff);
  return (["kalshi", "polymarket_us"] as VenueKey[]).flatMap((venue) =>
    (["yes", "no"] as SideKey[]).map((side) => {
      const points = downsample(visible.filter((point) => point.venue === venue && point.side === side), 600);
      const style = TRACE_STYLE[`${venue}:${side}`];
      const x = points.map((point) => new Date(point.ts).toISOString());
      return {
        x,
        y: points.map((point) => point.price),
        type: "scatter",
        mode: "lines",
        name: `${venue === "kalshi" ? "Kalshi" : "Polymarket US"} ${side.toUpperCase()}`,
        line: { color: style.color, width: 2, dash: style.dash },
      };
    }).filter((trace) => trace.x.length > 0) as Data[],
  );
}

export function displayPrice(book: RuntimeBook, side: SideKey) {
  const bid = quote(book, side, "bid");
  const ask = quote(book, side, "ask");
  return midpoint(bid, ask) ?? ask ?? bid;
}

export function quote(book: RuntimeBook | undefined, side: SideKey, kind: "bid" | "ask") {
  const key = `${side}_${kind}` as keyof RuntimeBook;
  const value = book?.[key];
  if (value === null || value === undefined) return null;
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? numberValue : null;
}

export function midpoint(bid: number | null, ask: number | null) {
  return bid !== null && ask !== null ? (bid + ask) / 2 : null;
}

function dedupePoints(points: HistoryPoint[]) {
  const seen = new Set<string>();
  return points.filter((point) => {
    const key = `${point.ts}:${point.outcome}:${point.venue}:${point.side}:${point.price}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function downsample(points: HistoryPoint[], maxPoints: number) {
  if (points.length <= maxPoints) return points;
  const step = Math.ceil(points.length / maxPoints);
  return points.filter((_, index) => index % step === 0);
}
