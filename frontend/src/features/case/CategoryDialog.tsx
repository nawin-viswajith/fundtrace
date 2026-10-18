import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "../../api/endpoints";
import { useCaseAction, useInvalidateCase } from "../../api/hooks";
import { InlineError, Note } from "../../components/Primitives";
import { Modal } from "../../components/Overlay";
import { useToast } from "../../components/Toast";
import { formatPct } from "../../lib/format";
import type { ClassifyResponse } from "../../types/api";

/** AI category suggestion, opened from the case header. A suggestion only — the investigator decides. */
export function CategoryDialog({
  caseId,
  currentCategory,
  categories,
  canEdit,
  onClose,
}: {
  caseId: string;
  currentCategory: string;
  categories?: Record<string, string>;
  canEdit: boolean;
  onClose: () => void;
}) {
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
      {
        onSuccess: () => {
          toast.show(`Category changed to ${res.label ?? res.suggested_category}`);
          onClose();
        },
      },
    );
  };
  return (
    <Modal
      open
      onClose={onClose}
      size="sm"
      title="Suggest a category"
      description="The AI reads the customer's statement and suggests what kind of dispute this is. It is only a suggestion — you decide."
      footer={
        <>
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Close
          </button>
          {res?.status === "ok" && !res.agrees && canEdit ? (
            <button type="button" className="btn btn-primary" onClick={apply} disabled={action.isPending}>
              Use “{res.label}”
            </button>
          ) : (
            <button type="button" className="btn btn-primary" onClick={() => classify.mutate()} disabled={classify.isPending}>
              {classify.isPending ? "Reading the statement…" : res ? "Ask again" : "Suggest a category"}
            </button>
          )}
        </>
      }
    >
      <p className="small">
        Current category: <strong>{categories?.[currentCategory] ?? currentCategory}</strong>
      </p>
      <InlineError error={classify.error} />
      {res && res.status !== "ok" && <Note tone="neutral">{res.message ?? "Not analysed"}</Note>}
      {res && res.status === "ok" && (
        <div className="classify-result">
          <p>
            Suggested: <strong>{res.label}</strong> — {res.agrees ? "the same as the current category." : "different from the current category."}
          </p>
          {res.rationale && <p className="small">{res.rationale}</p>}
          {res.translation && <p className="small">An English translation of the statement was saved to the case overview.</p>}
          <p className="small muted">
            How sure the AI was: {formatPct(res.token_confidence)} (a rough signal, not accuracy) · statement language {res.detected_language}
          </p>
        </div>
      )}
      <InlineError error={action.error} />
    </Modal>
  );
}
