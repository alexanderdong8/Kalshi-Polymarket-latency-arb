export function canActivateLive(confirmation: string, reconciliationReady: boolean) {
  return confirmation === "LIVE" && reconciliationReady;
}
