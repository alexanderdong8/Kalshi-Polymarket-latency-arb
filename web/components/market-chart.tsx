"use client";

import dynamic from "next/dynamic";
import type { Data, Layout } from "plotly.js";

const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });

export function MarketChart({
  title,
  traces,
  yTitle = "Price",
}: {
  title: string;
  traces: Data[];
  yTitle?: string;
}) {
  const layout: Partial<Layout> = {
    title: { text: title, font: { size: 13, color: "#2d322f" }, x: 0.02 },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    margin: { l: 48, r: 18, t: 46, b: 38 },
    height: 330,
    font: { family: "var(--font-mono)", size: 10, color: "#69706b" },
    xaxis: { gridcolor: "#e7e4dc", zeroline: false },
    yaxis: { title: { text: yTitle }, gridcolor: "#e7e4dc", zeroline: false },
    showlegend: true,
    legend: { orientation: "h", y: 1.12, x: 0.5, xanchor: "center" },
    hovermode: "x unified",
  };
  return (
    <Plot
      data={traces}
      layout={layout}
      config={{ displaylogo: false, responsive: true, modeBarButtonsToRemove: ["lasso2d", "select2d"] }}
      style={{ width: "100%", height: "330px" }}
      useResizeHandler
    />
  );
}
