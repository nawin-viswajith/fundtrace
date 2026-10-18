import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useCssVars } from "../../lib/cssVars";
import { formatIST, formatPct, formatUsd, humanize } from "../../lib/format";
import type { OpsMetrics } from "../../types/api";

interface ChartColors {
  c1: string;
  c2: string;
  grid: string;
  axis: string;
  surface: string;
  text: string;
  border: string;
}

function useChartColors(): ChartColors {
  return useCssVars({
    c1: ["--chart-1", "#1f3a7a"],
    c2: ["--chart-2", "#b45309"],
    grid: ["--chart-grid", "#e9ebef"],
    axis: ["--chart-axis", "#5f6673"],
    surface: ["--surface", "#ffffff"],
    text: ["--text", "#14181f"],
    border: ["--border-strong", "#c3c8d0"],
  });
}

const tooltipStyle = (c: ChartColors) => ({
  contentStyle: { background: c.surface, border: `1px solid ${c.border}`, borderRadius: 0, boxShadow: "none", color: c.text, fontSize: 12, padding: "6px 10px" },
  labelStyle: { color: c.text, fontWeight: 600 },
  itemStyle: { color: c.text },
});

export function CostPerDayChart({ data }: { data: OpsMetrics["per_day"] }) {
  const c = useChartColors();
  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid vertical={false} stroke={c.grid} />
        <XAxis dataKey="day" tick={{ fill: c.axis, fontSize: 11 }} axisLine={{ stroke: c.grid }} tickLine={false} />
        <YAxis tickFormatter={(v: number) => formatUsd(v)} tick={{ fill: c.axis, fontSize: 11 }} axisLine={false} tickLine={false} width={64} />
        <Tooltip {...tooltipStyle(c)} cursor={{ fill: c.grid, opacity: 0.6 }} formatter={(v: number, n: string) => (n === "cost_usd" ? [formatUsd(v), "Cost"] : [v, humanize(n)])} />
        <Bar dataKey="cost_usd" name="cost_usd" fill={c.c1} radius={0} maxBarSize={32} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function QualityTrendChart({ data }: { data: OpsMetrics["quality"]["hallucination_trend"] }) {
  const c = useChartColors();
  const rows = data.map((r, i) => ({ ...r, idx: i + 1, label: `${r.case_id} · ${formatIST(r.created_at)}` }));
  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        <CartesianGrid vertical={false} stroke={c.grid} />
        <XAxis dataKey="idx" tick={{ fill: c.axis, fontSize: 11 }} axisLine={{ stroke: c.grid }} tickLine={false} label={{ value: "Report #", position: "insideBottomRight", offset: -2, fill: c.axis, fontSize: 11 }} />
        <YAxis domain={[0, 1]} tickFormatter={(v: number) => formatPct(v)} tick={{ fill: c.axis, fontSize: 11 }} axisLine={false} tickLine={false} width={44} />
        <Tooltip
          {...tooltipStyle(c)}
          labelFormatter={(_, p) => {
            const r = p?.[0]?.payload as (typeof rows)[number] | undefined;
            return r ? `${r.label} (${r.generator === "deterministic" ? "facts only" : r.generator})` : "";
          }}
          formatter={(v, n) => [typeof v === "number" ? formatPct(v, 1) : "—", String(n)]}
        />
        <Legend wrapperStyle={{ fontSize: 12, color: c.text }} iconType="plainline" />
        <Line type="linear" dataKey="hallucination_rate" name="Hallucination rate" stroke={c.c2} strokeWidth={1.75} dot={{ r: 3, strokeWidth: 0, fill: c.c2 }} activeDot={{ r: 4.5, strokeWidth: 0 }} connectNulls />
        <Line type="linear" dataKey="confidence" name="Confidence" stroke={c.c1} strokeWidth={1.75} dot={{ r: 3, strokeWidth: 0, fill: c.c1 }} activeDot={{ r: 4.5, strokeWidth: 0 }} connectNulls />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function VerdictChart({ verdicts }: { verdicts: Record<string, number> }) {
  const c = useChartColors();
  const rows = Object.entries(verdicts).map(([k, v]) => ({ verdict: humanize(k), count: v }));
  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 24, bottom: 0, left: 8 }}>
        <CartesianGrid horizontal={false} stroke={c.grid} />
        <XAxis type="number" allowDecimals={false} tick={{ fill: c.axis, fontSize: 11 }} axisLine={false} tickLine={false} />
        <YAxis type="category" dataKey="verdict" tick={{ fill: c.axis, fontSize: 11 }} axisLine={false} tickLine={false} width={118} />
        <Tooltip {...tooltipStyle(c)} cursor={{ fill: c.grid, opacity: 0.5 }} formatter={(v: number) => [v, "Claims"]} />
        <Bar dataKey="count" fill={c.c1} radius={0} maxBarSize={18} label={{ position: "right", fill: c.axis, fontSize: 11 }} />
      </BarChart>
    </ResponsiveContainer>
  );
}
