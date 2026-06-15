"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { CheckCircle2, Database, KeyRound, ServerCog } from "lucide-react";
import { api } from "@/lib/api";
import type { Worker } from "@/lib/types";
import { PageHead, StatusBadge } from "@/components/ui";

type SettingsData = {
  credentials: Record<string, boolean>;
  connections: Record<string, { status: string; base_url: string }>;
  openai_available: boolean;
  storage: Record<string, string>;
  workers: Worker[];
  emergency_stop: boolean;
};

export default function SettingsPage() {
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api<SettingsData>("/settings") });
  const diagnostics = useMutation({ mutationFn: () => api<Record<string, { status: string; detail: unknown }>>("/settings/diagnostics", { method: "POST" }) });
  return (
    <>
      <PageHead eyebrow="06 / Local control" title="Settings & Diagnostics" description="Credential values stay in .env. This page reports presence, connectivity, storage, and worker health without revealing secrets." actions={<button className="button primary" onClick={() => diagnostics.mutate()}><ServerCog size={16} /> Run diagnostics</button>} />
      <div className="settings-grid">
        <section className="panel settings-card"><div className="settings-icon"><KeyRound /></div><h2>Credentials</h2>{Object.entries(settings.data?.credentials ?? {}).map(([name, ready]) => <div className="settings-row" key={name}><span>{name.replaceAll("_", " ")}</span><StatusBadge value={ready ? "configured" : "missing"} /></div>)}<div className="settings-row"><span>OpenAI event matching</span><StatusBadge value={settings.data?.openai_available ? "configured" : "unavailable"} /></div></section>
        <section className="panel settings-card"><div className="settings-icon"><CheckCircle2 /></div><h2>Venue connections</h2>{Object.entries(settings.data?.connections ?? {}).map(([name, value]) => <div className="settings-row stacked" key={name}><span>{name.replaceAll("_", " ")}</span><StatusBadge value={value.status} /><small>{value.base_url}</small></div>)}</section>
        <section className="panel settings-card"><div className="settings-icon"><Database /></div><h2>Local storage</h2>{Object.entries(settings.data?.storage ?? {}).map(([name, value]) => <div className="settings-row stacked" key={name}><span>{name.replaceAll("_", " ")}</span><small className="path">{value}</small></div>)}</section>
      </div>
      {diagnostics.data ? <section className="panel diagnostics"><div className="panel-title"><div><p className="eyebrow">Read-only checks</p><h2>Diagnostic results</h2></div></div>{Object.entries(diagnostics.data).map(([name, value]) => <div className="diagnostic-row" key={name}><b>{name.replaceAll("_", " ")}</b><StatusBadge value={value.status} /><pre>{JSON.stringify(value.detail, null, 2)}</pre></div>)}</section> : null}
    </>
  );
}
