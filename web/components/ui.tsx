import { AlertTriangle, Check, Clock3, X } from "lucide-react";

export function PageHead({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow: string;
  title: string;
  description: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="page-head">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p className="lede">{description}</p>
      </div>
      {actions ? <div className="head-actions">{actions}</div> : null}
    </div>
  );
}

export function StatusBadge({ value }: { value: string }) {
  const normalized = value.toLowerCase();
  const good = ["running", "complete", "approved", "passed", "connected"].includes(normalized);
  const bad = ["failed", "unavailable", "live"].includes(normalized);
  const Icon = good ? Check : bad ? X : Clock3;
  return (
    <span className={`status ${good ? "good" : bad ? "bad" : "neutral"}`}>
      <Icon size={12} /> {value.replaceAll("_", " ")}
    </span>
  );
}

export function Metric({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: string;
  detail?: string;
  tone?: "positive" | "risk";
}) {
  return (
    <div className={`metric ${tone ?? ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {detail ? <small>{detail}</small> : null}
    </div>
  );
}

export function EmptyState({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="empty-state">
      <AlertTriangle size={22} />
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}

export function Progress({ value }: { value: number }) {
  return <div className="progress"><span style={{ width: `${Math.round(value * 100)}%` }} /></div>;
}
