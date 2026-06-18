import assert from "node:assert/strict";
import test from "node:test";

import { appendHistory, buildTraces, displayPrice } from "@/lib/event-detail-state";
import type { RuntimeBook, RuntimeState } from "@/lib/types";

const NOW = Date.parse("2026-06-17T12:00:00.000Z");

function book(overrides: Partial<RuntimeBook> = {}): RuntimeBook {
  return {
    venue: "kalshi",
    outcome: "Ghana",
    received_ts: "2026-06-17T11:59:30.000Z",
    yes_bid: "0.40",
    yes_ask: "0.42",
    no_bid: "0.58",
    no_ask: "0.60",
    yes_bids: [["0.40", "100"]],
    yes_asks: [["0.42", "90"]],
    no_bids: [["0.58", "90"]],
    no_asks: [["0.60", "100"]],
    ...overrides,
  };
}

test("event detail history records yes and no prices from runtime books", () => {
  const state: RuntimeState = {
    books: {
      "kalshi:Ghana": book(),
      "polymarket_us:Ghana": book({
        venue: "polymarket_us",
        yes_bid: "0.39",
        yes_ask: "0.41",
        no_bid: "0.59",
        no_ask: "0.61",
      }),
    },
  };

  const points = appendHistory([], state, NOW);

  assert.equal(points.length, 4);
  assertApprox(points.find((point) => point.venue === "kalshi" && point.side === "yes")?.price, 0.41);
  assertApprox(points.find((point) => point.venue === "kalshi" && point.side === "no")?.price, 0.59);
  assertApprox(points.find((point) => point.venue === "polymarket_us" && point.side === "yes")?.price, 0.4);
  assertApprox(points.find((point) => point.venue === "polymarket_us" && point.side === "no")?.price, 0.6);
});

test("event detail chart filters to the selected window and outcome", () => {
  const history = [
    { ts: NOW - 20 * 60 * 1000, outcome: "Ghana", venue: "kalshi" as const, side: "yes" as const, price: 0.4 },
    { ts: NOW - 2 * 60 * 60 * 1000, outcome: "Ghana", venue: "kalshi" as const, side: "yes" as const, price: 0.45 },
    { ts: NOW - 10 * 60 * 1000, outcome: "Panama", venue: "kalshi" as const, side: "yes" as const, price: 0.2 },
  ];

  const thirty = buildTraces(history, "Ghana", "30m", NOW);
  const threeHour = buildTraces(history, "Ghana", "3h", NOW);

  assert.deepEqual(thirty[0].y, [0.4]);
  assert.deepEqual(threeHour[0].y, [0.4, 0.45]);
});

test("event detail display price prefers midpoint and falls back to one-sided quotes", () => {
  assertApprox(displayPrice(book({ yes_bid: "0.10", yes_ask: "0.20" }), "yes"), 0.15);
  assert.equal(displayPrice(book({ yes_bid: null, yes_ask: "0.22" }), "yes"), 0.22);
});

function assertApprox(actual: number | undefined | null, expected: number) {
  assert.notEqual(actual, undefined);
  assert.notEqual(actual, null);
  assert.ok(Math.abs(Number(actual) - expected) < 0.000001, `${actual} ~= ${expected}`);
}
