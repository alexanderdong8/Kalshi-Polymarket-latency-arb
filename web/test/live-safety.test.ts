import assert from "node:assert/strict";
import test from "node:test";

import { canActivateLive } from "@/lib/live-safety";

test("live activation requires exact confirmation and completed reconciliation", () => {
  assert.equal(canActivateLive("live", true), false);
  assert.equal(canActivateLive("LIVE", false), false);
  assert.equal(canActivateLive("LIVE", true), true);
});
