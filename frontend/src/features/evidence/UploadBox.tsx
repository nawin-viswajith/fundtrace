import { useRef, useState, type DragEvent, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { UploadCloud, X } from "lucide-react";
import { api } from "../../api/endpoints";
import { useInvalidateCase } from "../../api/hooks";
import { useWorkspace } from "../case/workspace";
import { Card, InlineError } from "../../components/Primitives";
import { useToast } from "../../components/Toast";
import { formatBytes } from "../../lib/format";
import type { ChecklistItem } from "../../types/api";

export const MAX_UPLOAD = 5 * 1024 * 1024;
const ACCEPT = ["image/png", "image/jpeg", "application/pdf", "text/plain"];
const EXT = /\.(png|jpe?g|pdf|txt)$/i;

export function validateUpload(f: File): string | null {
  if (f.size === 0) return "The file is empty.";
  if (f.size > MAX_UPLOAD) return `The file is ${formatBytes(f.size)}; the limit is 5 MB.`;
  if (!ACCEPT.includes(f.type) && !EXT.test(f.name)) return "Only PNG, JPG, PDF or TXT files can be uploaded.";
  return null;
}

const KINDS = [
  { v: "customer_upload", label: "Customer upload" },
  { v: "bank_record", label: "Bank record" },
  { v: "merchant_response", label: "Merchant response" },
  { v: "complaint_ack", label: "Complaint acknowledgement" },
];

export function UploadBox({ checklist }: { checklist: ChecklistItem[] }) {
  const { caseId, ctx } = useWorkspace();
  const invalidate = useInvalidateCase(caseId);
  const toast = useToast();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const [key, setKey] = useState(checklist.find((c) => c.key === "customer_evidence")?.key ?? checklist[0]?.key ?? "");
  const [kind, setKind] = useState("customer_upload");

  const upload = useMutation({
    mutationFn: () => api.uploadEvidence(caseId, file as File, key || null, kind),
    onSuccess: async (r) => {
      toast.show(`Uploaded as ${r.id}. Use Analyse to read it and compare with the ledger.`);
      setFile(null);
      if (input.current) input.current.value = "";
      await invalidate();
    },
  });

  const pick = (f: File | null | undefined) => {
    upload.reset();
    if (!f) return;
    const p = validateUpload(f);
    setProblem(p);
    setFile(p ? null : f);
  };
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDrag(false);
    pick(e.dataTransfer.files?.[0]);
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (file) upload.mutate();
  };

  return (
    <Card title="Upload evidence" subtitle="PNG, JPG, PDF or TXT, up to 5 MB. Files are hashed (SHA-256) and the upload is audited.">
      <form onSubmit={submit} className="stack">
        <div
          className={`dropzone ${drag ? "is-drag" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={onDrop}
        >
          <UploadCloud size={26} aria-hidden="true" />
          {file ? (
            <p className="drop-file">
              <strong className="break">{file.name}</strong> <span className="muted">{formatBytes(file.size)}</span>
              <button
                type="button"
                className="icon-btn icon-btn-sm"
                aria-label="Remove selected file"
                onClick={() => {
                  setFile(null);
                  if (input.current) input.current.value = "";
                }}
              >
                <X size={14} />
              </button>
            </p>
          ) : (
            <p>Drag a file here, or</p>
          )}
          <label className="btn btn-secondary btn-sm file-btn">
            Choose file
            <input
              ref={input}
              type="file"
              className="sr-only"
              accept=".png,.jpg,.jpeg,.pdf,.txt,image/png,image/jpeg,application/pdf,text/plain"
              onChange={(e) => pick(e.target.files?.[0])}
            />
          </label>
        </div>
        {problem && (
          <p className="inline-error" role="alert">
            {problem}
          </p>
        )}
        <div className="form-row">
          <label className="field">
            <span className="field-label">Checklist item</span>
            <select className="select" value={key} onChange={(e) => setKey(e.target.value)}>
              <option value="">Not linked to a checklist item</option>
              {checklist.map((c) => (
                <option key={c.key} value={c.key}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field-label">Kind</span>
            <select className="select" value={kind} onChange={(e) => setKind(e.target.value)}>
              {KINDS.map((k) => (
                <option key={k.v} value={k.v}>
                  {k.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <InlineError error={upload.error} />
        <button type="submit" className="btn btn-primary" disabled={!file || upload.isPending || !ctx.can_edit}>
          {upload.isPending ? "Uploading…" : "Upload"}
        </button>
      </form>
    </Card>
  );
}
