import { useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { MessageSquareText, Sparkles, Tags } from "lucide-react";
import { api } from "../../api/endpoints";
import { useCaseAction, useInvalidateCase } from "../../api/hooks";
import { Card, InlineError, Note } from "../../components/Primitives";
import { Chip } from "../../components/Chip";
import { useToast } from "../../components/Toast";
import { formatPct, formatUsd } from "../../lib/format";
import type { AskResponse, ClassifyResponse, SnapshotRecord } from "../../types/api";
import { ClaimView } from "./ClaimView";

export function CopilotBox({ caseId, records, onShowOnGraph }: { caseId: string; records: Record<string, SnapshotRecord>; onShowOnGraph?: (id: string) => void }) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<{ q: string; a: AskResponse } | null>(null);
  const ask = useMutation({
    mutationFn: (q: string) => api.ask(caseId, q),
    onSuccess: (a, q) => setAnswer({ q, a }),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const q = question.trim();
    if (q.length >= 3) ask.mutate(q);
  };
  return (
    <Card title="Ask about this case" subtitle="Answers cite records from the case snapshot and are checked like report claims.">
      <form onSubmit={submit} className="copilot-form">
        <label className="sr-only" htmlFor="copilot-q">
          Question
        </label>
        <textarea
          id="copilot-q"
          className="textarea"
          rows={2}
          placeholder="e.g. Which downstream accounts still hold funds?"
          value={question}
          maxLength={800}
          onChange={(e) => setQuestion(e.target.value)}
        />
        <button type="submit" className="btn btn-primary" disabled={question.trim().length < 3 || ask.isPending}>
          <MessageSquareText size={15} aria-hidden="true" /> {ask.isPending ? "Asking…" : "Ask"}
        </button>
      </form>
      <InlineError error={ask.error} />
      {answer && (
        <div className="copilot-answer" aria-live="polite">
          <p className="small muted">
            Q: <em>{answer.q}</em>
          </p>
          {answer.a.status !== "ok" ? (
            <Note tone="neutral">{answer.a.message ?? "Not analysed"}</Note>
          ) : (
            <>
              {answer.a.insufficient_data && <Note tone="warn">The records do not contain enough to answer this fully.</Note>}
              <ol className="claim-list">
                {answer.a.claims.map((c, i) => (
                  <ClaimView key={c.id ?? i} claim={{ ...c, id: c.id ?? `A${i + 1}` }} records={records} onShowOnGraph={onShowOnGraph} strictCitations={false} />
                ))}
              </ol>
              {answer.a.follow_up_questions && answer.a.follow_up_questions.length > 0 && (
                <div className="followups">
                  {answer.a.follow_up_questions.map((f) => (
                    <button key={f} type="button" className="chip chip-btn chip-neutral" onClick={() => setQuestion(f)}>
                      {f}
                    </button>
                  ))}
                </div>
              )}
              <p className="small muted">
                {answer.a.model} · {formatUsd(answer.a.cost_usd)} · {answer.a.flagged ?? 0} flagged
              </p>
            </>
          )}
        </div>
      )}
    </Card>
  );
}

export function ClassifyPanel({ caseId, currentCategory, categories, canEdit }: { caseId: string; currentCategory: string; categories?: Record<string, string>; canEdit: boolean }) {
  const toast = useToast();
  const invalidate = useInvalidateCase(caseId);
  const action = useCaseAction(caseId);
  const [res, setRes] = useState<ClassifyResponse | null>(null);
  const classify = useMutation({
    mutationFn: () => api.classify(caseId),
    onSuccess: async (r) => {
      setRes(r);
      if (r.status === "ok") await invalidate();
    },
  });
  const apply = () => {
    if (!res?.suggested_category) return;
    action.mutate(
      { type: "recategorise", category: res.suggested_category, reason: `Applied AI suggestion: ${res.rationale ?? ""}`.slice(0, 500), from_ai: true },
      { onSuccess: () => toast.show(`Category changed to ${res.label ?? res.suggested_category}`) },
    );
  };
  return (
    <Card title="AI category suggestion" subtitle="Gemini reads the customer statement and suggests a category. Suggestion only — you decide.">
      <button type="button" className="btn btn-secondary" onClick={() => classify.mutate()} disabled={classify.isPending}>
        <Tags size={15} aria-hidden="true" /> {classify.isPending ? "Classifying…" : "Suggest a category"}
      </button>
      <InlineError error={classify.error} />
      {res && res.status !== "ok" && <Note tone="neutral">{res.message ?? "Not analysed"}</Note>}
      {res && res.status === "ok" && (
        <div className="classify-result">
          <p>
            Suggested: <strong>{res.label}</strong>{" "}
            <Chip tone={res.agrees ? "good" : "warn"} size="sm">
              {res.agrees ? "Agrees with current category" : `Current: ${categories?.[currentCategory] ?? currentCategory}`}
            </Chip>
          </p>
          {res.rationale && <p className="small">{res.rationale}</p>}
          <p className="small muted">
            Token confidence {formatPct(res.token_confidence)} (from average log-probability — a coarse certainty signal, not accuracy) ·{" "}
            {res.model} · language {res.detected_language}
          </p>
          {res.translation && (
            <p className="small">
              <Sparkles size={12} aria-hidden="true" /> Translation saved to the case overview.
            </p>
          )}
          <p className="small muted">{res.note}</p>
          {!res.agrees && canEdit && (
            <button type="button" className="btn btn-primary btn-sm" onClick={apply} disabled={action.isPending}>
              Apply suggestion
            </button>
          )}
          <InlineError error={action.error} />
        </div>
      )}
    </Card>
  );
}
