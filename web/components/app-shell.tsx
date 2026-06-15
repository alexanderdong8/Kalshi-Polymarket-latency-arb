"use client";

import {
  Activity,
  BookOpen,
  CircleDollarSign,
  FlaskConical,
  Gauge,
  Radio,
  Search,
  Settings,
  ShieldAlert,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

const links = [
  { href: "/discover", label: "Discover", icon: Search },
  { href: "/markets", label: "My Markets", icon: BookOpen },
  { href: "/paper", label: "Paper", icon: FlaskConical },
  { href: "/live", label: "Live", icon: Radio },
  { href: "/backtests", label: "Backtests", icon: Activity },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const queryClient = useQueryClient();
  const health = useQuery({
    queryKey: ["health"],
    queryFn: () => api<{ status: string; workers: number; emergency_stop: boolean }>("/health"),
  });
  const emergency = useMutation({
    mutationFn: (active: boolean) =>
      api("/emergency-stop", { method: "POST", body: JSON.stringify({ active }) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["health"] }),
  });

  return (
    <div className="app-frame">
      <aside className="sidebar">
        <Link href="/discover" className="brand" aria-label="Arbiter home">
          <span className="brand-mark"><Gauge size={18} /></span>
          <span><b>Arbiter</b><small>LOCAL TRADING DESK</small></span>
        </Link>
        <nav aria-label="Primary navigation">
          {links.map(({ href, label, icon: Icon }) => (
            <Link
              href={href}
              key={href}
              className={pathname.startsWith(href) ? "nav-link active" : "nav-link"}
            >
              <Icon size={17} strokeWidth={1.8} />
              <span>{label}</span>
            </Link>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="connection-row">
            <span className={health.isSuccess ? "pulse-dot" : "pulse-dot offline"} />
            <span>{health.isSuccess ? "Control service online" : "Connecting..."}</span>
          </div>
          <button
            className={health.data?.emergency_stop ? "emergency active" : "emergency"}
            onClick={() => emergency.mutate(!health.data?.emergency_stop)}
          >
            <ShieldAlert size={16} />
            {health.data?.emergency_stop ? "Release emergency stop" : "Emergency stop"}
          </button>
        </div>
      </aside>
      <main className="main-shell">
        <header className="topbar">
          <div className="market-clock">
            <CircleDollarSign size={15} />
            <span>Kalshi + Polymarket US</span>
            <i />
            <span>{health.data?.workers ?? 0} local workers</span>
          </div>
          <div className="local-badge"><span /> Single-user local</div>
        </header>
        <div className="page-wrap">{children}</div>
      </main>
    </div>
  );
}
