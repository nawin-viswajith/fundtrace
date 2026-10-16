import type { ReactNode } from "react";
import { BASIS_LABELS, PROVENANCE, provenanceStyle, ruleStatusInfo, SEVERITY, VERDICT_LABELS } from "../lib/labels";
import type { Severity } from "../types/api";

export type Tone = "good" | "warn" | "bad" | "neutral" | "accent";

interface ChipProps {
  tone?: Tone | string;
  children: ReactNode;
  title?: string;
  icon?: ReactNode;
  className?: string;
  size?: "sm" | "md";
}

export function Chip({ tone = "neutral", children, title, icon, className = "", size = "md" }: ChipProps) {
  return (
    <span className={`chip chip-${tone} ${size === "sm" ? "chip-sm" : ""} ${className}`} title={title}>
      {icon}
      {children}
    </span>
  );
}

export function ProvenanceChip({ provenance, size, showMeaning }: { provenance: string; size?: "sm" | "md"; showMeaning?: boolean }) {
  const s = provenanceStyle(provenance);
  return (
    <Chip tone={`prov-${s.tone}`} title={`${s.label}: ${s.meaning}`} size={size}>
      <span className={`prov-swatch prov-swatch-${s.tone}`} aria-hidden="true" />
      {s.label}
      {showMeaning && <span className="chip-meaning">— {s.meaning}</span>}
    </Chip>
  );
}

export function SeverityChip({ severity, size }: { severity: Severity | string; size?: "sm" | "md" }) {
  const s = SEVERITY[severity as Severity];
  return (
    <Chip tone={`sev-${severity}`} size={size} title={`Severity: ${s?.label ?? severity}`}>
      {s?.label ?? severity}
    </Chip>
  );
}

export function RuleStatusChip({ status, size }: { status: string; size?: "sm" | "md" }) {
  const s = ruleStatusInfo(status);
  return (
    <Chip tone={`rule-${s.tone}`} size={size} title={s.hint}>
      {s.label}
    </Chip>
  );
}

export function BasisChip({ basis }: { basis: string }) {
  const b = BASIS_LABELS[basis] ?? { label: basis, tone: "unknown", hint: "" };
  return (
    <Chip tone={`prov-${b.tone}`} size="sm" title={`Basis — ${b.label}: ${b.hint}`}>
      <span className={`prov-swatch prov-swatch-${b.tone}`} aria-hidden="true" />
      {b.label}
    </Chip>
  );
}

export function VerdictChip({ verdict }: { verdict: string }) {
  const v = VERDICT_LABELS[verdict] ?? { label: verdict, tone: "neutral" as const, hint: "" };
  return (
    <Chip tone={v.tone} size="sm" title={`Fact-check: ${v.hint}`}>
      {v.label}
    </Chip>
  );
}

export { PROVENANCE };
