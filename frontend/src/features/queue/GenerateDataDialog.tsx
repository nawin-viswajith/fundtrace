import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type GenerateDataRequest, type GenerateDataResult } from "../../api/endpoints";
import { useMeta } from "../../api/hooks";
import { InlineError, Note } from "../../components/Primitives";
import { Modal } from "../../components/Overlay";

const STATUS_CHOICES: [string, string][] = [
  ["mixed", "A realistic mix (some new, some in progress, a few decided)"],
  ["new", "All New"],
  ["triage", "All in Triage"],
  ["investigating", "All being investigated"],
  ["awaiting_evidence", "All waiting for the customer's evidence"],
  ["ready_for_review", "All ready for review"],
  ["resolved", "All decided"],
];

/** Generate more synthetic disputes (supervisors and admins): asks how many, what kind, amounts, status, AI budget. */
export function GenerateDataDialog({ onClose }: { onClose: () => void }) {
  const meta = useMeta();
  const qc = useQueryClient();
  const categories = meta.data?.categories ?? {};
  const investigators = (meta.data?.assignees ?? []).filter((a) => a.role === "investigator" || a.role === "supervisor");
  const [f, setF] = useState<GenerateDataRequest>({
    count: 5,
    categories: [],
    amount_min: 5000,
    amount_max: 100000,
    status_mode: "mixed",
    assign: "spread",
    days_back: 7,
    with_trail: true,
    with_evidence: true,
    statements: "template",
    ai_budget_usd: 0.1,
  });
  const [result, setResult] = useState<GenerateDataResult | null>(null);
  const set = (patch: Partial<GenerateDataRequest>) => setF((p) => ({ ...p, ...patch }));
  const chosen = f.categories.length ? f.categories : Object.keys(categories);
  const gen = useMutation({
    mutationFn: () => api.generateData({ ...f, categories: chosen }),
    onSuccess: async (r) => {
      setResult(r);
      await qc.invalidateQueries({ queryKey: ["cases"] });
      await qc.invalidateQueries({ queryKey: ["overview"] });
    },
  });
  const toggleCat = (k: string) =>
    set({ categories: (f.categories.length ? f.categories : Object.keys(categories)).includes(k) ? chosen.filter((c) => c !== k) : [...chosen, k] });
  // Boxes may be empty while someone types; check the values instead of forcing them.
  const amountError =
    !Number.isInteger(f.count) || f.count < 1 || f.count > 50
      ? "Choose between 1 and 50 cases."
      : f.amount_min < 100 || f.amount_max < 100 || f.amount_max > 1000000
        ? "Payments must be between ₹100 and ₹10,00,000."
        : f.amount_min > f.amount_max
          ? "The lowest amount must not be above the highest."
          : f.days_back < 1 || f.days_back > 30
            ? "Choose between 1 and 30 days."
            : f.statements === "ai" && (f.ai_budget_usd < 0 || f.ai_budget_usd > 2)
              ? "The AI budget must be between $0 and $2."
              : null;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!amountError && chosen.length) gen.mutate();
  };

  return (
    <Modal
      open
      onClose={onClose}
      size="lg"
      title="Generate demo disputes"
      description="Creates complete synthetic cases — payment, money trail, sign-in records, receipt and status — from existing demo customers. Everything generated is marked synthetic and recorded in the audit trail."
      footer={
        result ? (
          <button type="button" className="btn btn-primary" onClick={onClose}>
            Done
          </button>
        ) : (
          <>
            <button type="button" className="btn btn-ghost" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" form="gen-form" className="btn btn-primary" disabled={gen.isPending || !!amountError || !chosen.length}>
              {gen.isPending ? "Generating…" : `Generate ${f.count} case${f.count === 1 ? "" : "s"}`}
            </button>
          </>
        )
      }
    >
      {result ? (
        <div className="stack">
          <Note tone="good">
            <strong>{result.created.length} cases created.</strong> Statements: {result.statements.template} from templates
            {result.statements.ai ? `, ${result.statements.ai} written by AI ($${result.statements.ai_cost_usd.toFixed(4)})` : ""}
            {result.statements.ai_rejected ? ` · ${result.statements.ai_rejected} AI statement(s) rejected (wrong amount) and replaced by a template` : ""}.
          </Note>
          {f.statements === "ai" && !result.statements.ai_available && (
            <Note tone="info">The AI is not available in this environment, so ready-made wording was used and nothing was spent.</Note>
          )}
          <div className="table-wrap">
            <table className="table table-compact">
              <thead>
                <tr>
                  <th scope="col">Case</th>
                  <th scope="col">Type of dispute</th>
                  <th scope="col" className="ta-r">Amount</th>
                  <th scope="col">Status</th>
                  <th scope="col">Priority</th>
                </tr>
              </thead>
              <tbody>
                {result.created.map((c) => (
                  <tr key={c.case_id}>
                    <td>
                      <Link to={`/cases/${c.case_id}`} className="link mono" onClick={onClose}>
                        {c.case_id}
                      </Link>
                    </td>
                    <td>{c.category}</td>
                    <td className="ta-r num">{c.amount}</td>
                    <td>{c.status.replace(/_/g, " ")}</td>
                    <td>{c.priority}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <form id="gen-form" onSubmit={submit} className="gen-form">
          <label className="field">
            <span className="field-label">How many cases (1–50)</span>
            <input className="input num" type="number" min={1} max={50} value={f.count} onChange={(e) => set({ count: Number(e.target.value) })} />
          </label>
          <fieldset className="gen-fieldset">
            <legend className="field-label">Types of dispute</legend>
            <div className="gen-checks">
              {Object.entries(categories).map(([k, label]) => (
                <label key={k} className="switch">
                  <input type="checkbox" checked={chosen.includes(k)} onChange={() => toggleCat(k)} />
                  <span>{label}</span>
                </label>
              ))}
            </div>
          </fieldset>
          <div className="gen-row">
            <label className="field">
              <span className="field-label">Lowest payment (₹)</span>
              <input className="input num" type="number" min={100} max={1000000} step={100} value={f.amount_min} onChange={(e) => set({ amount_min: Number(e.target.value) })} />
            </label>
            <label className="field">
              <span className="field-label">Highest payment (₹)</span>
              <input className="input num" type="number" min={100} max={1000000} step={100} value={f.amount_max} onChange={(e) => set({ amount_max: Number(e.target.value) })} />
            </label>
            <label className="field">
              <span className="field-label">Payments made in the last (days)</span>
              <input className="input num" type="number" min={1} max={30} value={f.days_back} onChange={(e) => set({ days_back: Number(e.target.value) })} />
            </label>
          </div>
          {amountError && <p className="inline-error">{amountError}</p>}
          <div className="gen-row">
            <label className="field">
              <span className="field-label">Status of the new cases</span>
              <select className="select" value={f.status_mode} onChange={(e) => set({ status_mode: e.target.value })}>
                {STATUS_CHOICES.map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span className="field-label">Assign to</span>
              <select className="select" value={f.assign} onChange={(e) => set({ assign: e.target.value })}>
                <option value="spread">Share across investigators</option>
                <option value="nobody">Nobody (unassigned)</option>
                {investigators.map((a) => (
                  <option key={a.id} value={a.username}>
                    {a.full_name.replace(/\s*\(synthetic\)\s*$/i, "")}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="gen-checks">
            <label className="switch">
              <input type="checkbox" checked={f.with_trail} onChange={(e) => set({ with_trail: e.target.checked })} />
              <span>Include a money trail for fraud cases (onward transfers, some money left to hold)</span>
            </label>
            <label className="switch">
              <input type="checkbox" checked={f.with_evidence} onChange={(e) => set({ with_evidence: e.target.checked })} />
              <span>Include a customer receipt screenshot for fraud and card cases</span>
            </label>
          </div>
          <fieldset className="gen-fieldset">
            <legend className="field-label">Customer statements</legend>
            <label className="switch">
              <input type="radio" name="stmt" checked={f.statements === "template"} onChange={() => set({ statements: "template" })} />
              <span>Use ready-made wording (free)</span>
            </label>
            <label className="switch">
              <input type="radio" name="stmt" checked={f.statements === "ai"} onChange={() => set({ statements: "ai" })} />
              <span>Have the AI write varied statements, within a budget</span>
            </label>
            {f.statements === "ai" && (
              <div className="gen-budget">
                <label className="field">
                  <span className="field-label">AI budget (US$, up to 2.00)</span>
                  <input
                    className="input num"
                    type="number"
                    min={0}
                    max={2}
                    step={0.05}
                    value={f.ai_budget_usd}
                    aria-describedby="gen-budget-help"
                    onChange={(e) => set({ ai_budget_usd: Number(e.target.value) })}
                  />
                </label>
                <p id="gen-budget-help" className="small muted">
                  About $0.001 per statement. When the budget runs out, or the AI is unavailable, ready-made wording is used. A statement with the wrong amount is
                  rejected.
                </p>
              </div>
            )}
          </fieldset>
          <InlineError error={gen.error} />
        </form>
      )}
    </Modal>
  );
}
