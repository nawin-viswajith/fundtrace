import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { History, Pencil } from "lucide-react";
import { api } from "../../api/endpoints";
import { useRuleHistory, useRules } from "../../api/hooks";
import { useAuth, canSupervise } from "../auth/AuthProvider";
import { EmptyState, ErrorState, InlineError, LoadingBlock, Note, Time } from "../../components/Primitives";
import { SeverityChip, Chip } from "../../components/Chip";
import { SectionTitle } from "../../components/Domain";
import { Modal } from "../../components/Overlay";
import { useToast } from "../../components/Toast";
import { humanize } from "../../lib/format";
import type { RuleCatalogueEntry } from "../../types/api";

function Params({ p, defaults }: { p: Record<string, number>; defaults?: Record<string, number> }) {
  const e = Object.entries(p);
  if (!e.length) return <span className="muted">—</span>;
  return (
    <dl className="param-list param-inline">
      {e.map(([k, v]) => (
        <div key={k} className={defaults && defaults[k] !== v ? "is-changed" : ""} title={defaults && defaults[k] !== v ? `Default ${defaults[k]}` : undefined}>
          <dt>{humanize(k)}</dt>
          <dd className="num">{String(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

export default function RulesPage() {
  const { user } = useAuth();
  const sup = canSupervise(user);
  const q = useRules();
  const [edit, setEdit] = useState<RuleCatalogueEntry | null>(null);
  const [hist, setHist] = useState<RuleCatalogueEntry | null>(null);

  return (
    <div className="page">
      <SectionTitle>Rule catalogue</SectionTitle>
      <p className="page-lede">
        Deterministic fraud-signal rules. Each one returns triggered, not triggered, or not evaluable (data missing) — never a verdict.
      </p>
      {!sup && <Note tone="neutral">Read-only: only supervisors and admins can change rule parameters.</Note>}
      {q.isLoading ? (
        <LoadingBlock label="Loading rules" lines={8} />
      ) : q.error ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} title="Couldn't load rules" />
      ) : !q.data?.rules.length ? (
        <EmptyState title="No rules configured" />
      ) : (
        <div className="table-wrap">
          <table className="table rules-table">
            <caption className="sr-only">Rules</caption>
            <thead>
              <tr>
                <th scope="col">Rule</th>
                <th scope="col">Severity</th>
                <th scope="col">Version</th>
                <th scope="col">Enabled</th>
                <th scope="col">Parameters</th>
                <th scope="col">Needs</th>
                <th scope="col">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {q.data.rules.map((r) => (
                <tr key={r.rule_id}>
                  <td data-label="Rule">
                    <strong>{r.name}</strong> <span className="mono small muted">{r.rule_id}</span>
                    <span className="cell-sub">{r.description}</span>
                  </td>
                  <td data-label="Severity">
                    <SeverityChip severity={r.severity} size="sm" />
                  </td>
                  <td data-label="Version" className="num">
                    v{r.version}
                  </td>
                  <td data-label="Enabled">
                    <Chip tone={r.enabled ? "good" : "neutral"} size="sm">
                      {r.enabled ? "Enabled" : "Disabled"}
                    </Chip>
                  </td>
                  <td data-label="Parameters">
                    <Params p={r.params} defaults={r.default_params} />
                  </td>
                  <td data-label="Needs" className="small">
                    {r.needs.join("; ")}
                  </td>
                  <td data-label="Actions">
                    <div className="btn-row nowrap">
                      <button type="button" className="btn btn-ghost btn-sm" onClick={() => setHist(r)} aria-label={`History of ${r.rule_id}`}>
                        <History size={14} aria-hidden="true" /> History
                      </button>
                      {sup && (
                        <button type="button" className="btn btn-secondary btn-sm" onClick={() => setEdit(r)} aria-label={`Edit ${r.rule_id}`}>
                          <Pencil size={14} aria-hidden="true" /> Edit
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {edit && <RuleEditor rule={edit} onClose={() => setEdit(null)} />}
      {hist && <RuleHistory rule={hist} onClose={() => setHist(null)} />}
    </div>
  );
}

function RuleEditor({ rule, onClose }: { rule: RuleCatalogueEntry; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [vals, setVals] = useState<Record<string, string>>(() => Object.fromEntries(Object.entries(rule.params).map(([k, v]) => [k, String(v)])));
  const [enabled, setEnabled] = useState(rule.enabled);
  const [note, setNote] = useState("");
  const parsed = Object.fromEntries(Object.entries(vals).map(([k, v]) => [k, Number(v)]));
  const bad = Object.entries(vals).filter(([, v]) => v.trim() === "" || !Number.isFinite(Number(v)) || Number(v) < 0).map(([k]) => k);
  const valid = bad.length === 0 && note.trim().length >= 5;
  const save = useMutation({
    mutationFn: () => api.updateRule(rule.rule_id, { params: parsed, enabled, change_note: note.trim() }),
    onSuccess: async (r) => {
      toast.show(`${rule.rule_id} saved as v${r.version}; all cases re-assessed`);
      await Promise.all([qc.invalidateQueries({ queryKey: ["rules"] }), qc.invalidateQueries({ queryKey: ["rule-history"] }), qc.invalidateQueries({ queryKey: ["case"] }), qc.invalidateQueries({ queryKey: ["cases"] })]);
      onClose();
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (valid) save.mutate();
  };
  return (
    <Modal
      open
      onClose={onClose}
      title={`Edit ${rule.rule_id} · ${rule.name}`}
      description="Changes create a new rule version, are audited, and re-evaluate every case."
      footer={
        <>
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" form="rule-form" className="btn btn-primary" disabled={!valid || save.isPending}>
            {save.isPending ? "Saving…" : "Save new version"}
          </button>
        </>
      }
    >
      <form id="rule-form" onSubmit={submit}>
        {Object.keys(vals).length === 0 && <p className="muted small">This rule has no numeric parameters.</p>}
        <div className="form-grid">
          {Object.entries(vals).map(([k, v]) => (
            <label key={k} className="field">
              <span className="field-label">
                {humanize(k)} <span className="muted">(default {rule.default_params[k]})</span>
              </span>
              <input
                className={`input num ${bad.includes(k) ? "is-invalid" : ""}`}
                type="number"
                step="any"
                min={0}
                value={v}
                onChange={(e) => setVals((s) => ({ ...s, [k]: e.target.value }))}
                aria-invalid={bad.includes(k)}
              />
            </label>
          ))}
        </div>
        <label className="switch">
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          <span>Rule enabled</span>
        </label>
        <label className="field">
          <span className="field-label">Change note (at least 5 characters)</span>
          <textarea className="textarea" rows={2} value={note} onChange={(e) => setNote(e.target.value)} maxLength={255} />
        </label>
        <InlineError error={save.error} />
      </form>
    </Modal>
  );
}

function RuleHistory({ rule, onClose }: { rule: RuleCatalogueEntry; onClose: () => void }) {
  const q = useRuleHistory(rule.rule_id);
  return (
    <Modal open onClose={onClose} title={`History · ${rule.rule_id} ${rule.name}`} size="lg">
      {q.isLoading ? (
        <LoadingBlock lines={4} />
      ) : q.error ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : !q.data?.versions.length ? (
        <EmptyState title="No changes yet">This rule still runs on its default parameters (v1).</EmptyState>
      ) : (
        <ol className="history-list">
          {q.data.versions.map((v) => (
            <li key={v.version}>
              <div className="history-head">
                <strong>v{v.version}</strong> <Chip tone={v.enabled ? "good" : "neutral"} size="sm">{v.enabled ? "Enabled" : "Disabled"}</Chip>
                <span className="muted small">
                  {v.by} · <Time iso={v.at} />
                </span>
              </div>
              <p className="small">“{v.note}”</p>
              <Params p={v.params} />
            </li>
          ))}
        </ol>
      )}
    </Modal>
  );
}
