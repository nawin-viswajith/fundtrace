import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { MessageCircle, Send, X } from "lucide-react";
import { api } from "../../api/endpoints";
import { errorMessage } from "../../api/client";
import { IdChip } from "../../components/Domain";
import { isGraphId } from "../../lib/labels";
import type { AssistantReply, AssistantTab } from "../../types/api";
import { useWorkspace, type TabId } from "./workspace";
import { OPEN_SECTION_EVENT } from "../report/ReportView";

interface Turn {
  role: "user" | "assistant";
  text: string;
  reply?: AssistantReply;
  error?: boolean;
}

const SUGGESTIONS = [
  "Summarise this case in simple words",
  "Where did the money go?",
  "What evidence is still missing?",
  "What should I do next?",
  "Clear the Limitations section of the AI report",
];
const TAB_NAMES: Record<AssistantTab, string> = {
  overview: "Overview",
  graph: "Money trail",
  timeline: "Timeline",
  risk: "Warning signs",
  evidence: "Evidence",
  report: "AI report",
  audit: "Notes & history",
};

function load(caseId: string): Turn[] {
  try {
    return JSON.parse(sessionStorage.getItem(`ft-assistant-${caseId}`) ?? "[]") as Turn[];
  } catch {
    return [];
  }
}

function store(caseId: string, turns: Turn[]) {
  try {
    sessionStorage.setItem(`ft-assistant-${caseId}`, JSON.stringify(turns.slice(-30)));
  } catch {
    /* storage unavailable: the conversation just isn't remembered */
  }
}

/** Open a report section (sections start collapsed) and scroll to it once the AI report tab has rendered it. */
function focusSection(key: string, tries = 30) {
  window.dispatchEvent(new CustomEvent(OPEN_SECTION_EVENT, { detail: key }));
  const el = document.getElementById(`report-section-${key}`);
  if (el) {
    el.scrollIntoView({ behavior: "smooth", block: "start" });
    el.classList.add("is-focused");
    window.setTimeout(() => el.classList.remove("is-focused"), 2200);
  } else if (tries > 0) window.setTimeout(() => focusSection(key, tries - 1), 100);
}

/** The floating case assistant: answers questions about this case and edits the AI report draft on request. */
export function CaseAssistant() {
  const { caseId, setTab, showOnGraph } = useWorkspace();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [turns, setTurns] = useState<Turn[]>(() => load(caseId));
  const [text, setText] = useState("");
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Get out of the way while reading: hide the button when scrolling down, bring it back on scroll up.
  const [tucked, setTucked] = useState(false);
  useEffect(() => {
    const last = new WeakMap<object, number>();
    const onScroll = (e: Event) => {
      const t = e.target as Document | HTMLElement;
      const el = t instanceof Document ? document.scrollingElement ?? document.documentElement : t;
      if (!(el instanceof HTMLElement)) return;
      const y = el.scrollTop;
      const prev = last.get(el) ?? 0; // pages start at the top
      last.set(el, y);
      const nearEnd = el.scrollHeight - el.clientHeight - y < 80;
      if (y < 40 || nearEnd || y < prev - 4) setTucked(false);
      else if (y > prev + 4) setTucked(true);
    };
    document.addEventListener("scroll", onScroll, { passive: true, capture: true });
    return () => document.removeEventListener("scroll", onScroll, { capture: true });
  }, []);

  useEffect(() => setTurns(load(caseId)), [caseId]);
  useEffect(() => store(caseId, turns), [caseId, turns]);
  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [turns, open]);
  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  const send = useMutation({
    mutationFn: (message: string) =>
      api.assistant(
        caseId,
        message,
        turns.slice(-6).map((t) => ({ role: t.role, text: t.reply ? replyText(t.reply) : t.text })),
      ),
    onSuccess: async (reply) => {
      setTurns((prev) => [...prev, { role: "assistant", text: reply.text ?? "", reply }]);
      if (reply.action?.changed) await qc.invalidateQueries({ queryKey: ["report"] });
    },
    onError: (e) => setTurns((prev) => [...prev, { role: "assistant", text: errorMessage(e), error: true }]),
  });

  const submit = (msg: string) => {
    const m = msg.trim();
    if (!m || send.isPending) return;
    setTurns((prev) => [...prev, { role: "user", text: m }]);
    setText("");
    send.mutate(m);
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit(text);
    }
  };
  const goTo = (tab: AssistantTab, section?: string | null) => {
    setTab(tab as TabId);
    if (section) focusSection(section);
  };

  return (
    <>
      {open && (
        <section className="assistant-panel" role="dialog" aria-label={`Case assistant for ${caseId}`}>
          <header className="assistant-head">
            <div>
              <strong>Case assistant</strong>
              <span className="small muted"> · {caseId}</span>
            </div>
            <span className="assistant-head-actions">
              {turns.length > 0 && (
                <button type="button" className="link-btn small" onClick={() => setTurns([])}>
                  New chat
                </button>
              )}
              <button type="button" className="icon-btn" aria-label="Close the assistant" onClick={() => setOpen(false)}>
                <X size={18} />
              </button>
            </span>
          </header>
          <div className="assistant-list" ref={listRef} aria-live="polite">
            {turns.length === 0 && (
              <div className="assistant-welcome">
                <p>
                  Ask me anything about this case. I answer only from the case records and show where each fact comes from. I can also tidy up
                  the AI report for you — changes stay in a draft until you save them.
                </p>
                <div className="assistant-suggest">
                  {SUGGESTIONS.map((s) => (
                    <button key={s} type="button" className="assistant-chip" onClick={() => submit(s)}>
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {turns.map((t, i) =>
              t.role === "user" ? (
                <div key={i} className="msg msg-user">
                  {t.text}
                </div>
              ) : (
                <AssistantMessage key={i} turn={t} onGo={goTo} onShowOnGraph={(id) => showOnGraph([id])} onAsk={submit} />
              ),
            )}
            {send.isPending && <div className="msg msg-bot msg-typing">Looking at the case records…</div>}
          </div>
          <form
            className="assistant-form"
            onSubmit={(e: FormEvent) => {
              e.preventDefault();
              submit(text);
            }}
          >
            <label className="sr-only" htmlFor="assistant-input">
              Message
            </label>
            <textarea
              id="assistant-input"
              ref={inputRef}
              className="textarea"
              rows={2}
              maxLength={1000}
              placeholder="Type a question, e.g. “Which accounts still have the money?”"
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={onKey}
            />
            <button type="submit" className="btn btn-primary" disabled={!text.trim() || send.isPending} aria-label="Send">
              <Send size={16} aria-hidden="true" />
            </button>
          </form>
        </section>
      )}
      <button
        type="button"
        className={`assistant-fab ${open ? "is-open" : ""} ${tucked && !open ? "is-tucked" : ""}`}
        aria-expanded={open}
        aria-label={open ? "Close the case assistant" : "Open the case assistant"}
        onClick={() => setOpen((o) => !o)}
      >
        {open ? <X size={22} aria-hidden="true" /> : <MessageCircle size={22} aria-hidden="true" />}
        {!open && <span className="assistant-fab-label">Ask about this case</span>}
      </button>
    </>
  );
}

function replyText(r: AssistantReply): string {
  return [r.text, ...r.claims.map((c) => c.text)].filter(Boolean).join(" ");
}

function AssistantMessage({
  turn,
  onGo,
  onShowOnGraph,
  onAsk,
}: {
  turn: Turn;
  onGo: (tab: AssistantTab, section?: string | null) => void;
  onShowOnGraph: (id: string) => void;
  onAsk: (q: string) => void;
}) {
  const r = turn.reply;
  if (!r)
    return (
      <div className={`msg msg-bot ${turn.error ? "msg-error" : ""}`} role={turn.error ? "alert" : undefined}>
        {turn.text}
      </div>
    );
  const nav = r.navigate;
  return (
    <div className="msg msg-bot">
      {r.text && <p>{r.text}</p>}
      {r.claims.length > 0 && (
        <ul className="msg-claims">
          {r.claims.map((c) => (
            <li key={c.id} className={c.flagged ? "is-flagged" : ""}>
              <span>{c.text}</span>
              {c.citations.length > 0 && (
                <span className="msg-cites">
                  {c.citations.map((id) => (
                    <IdChip
                      key={id}
                      id={id}
                      onClick={isGraphId(id) ? () => onShowOnGraph(id) : undefined}
                      title={isGraphId(id) ? "Show on the money trail" : "Record this sentence comes from"}
                    />
                  ))}
                </span>
              )}
              {c.flagged && <span className="small msg-warn"> This sentence did not pass the automatic checks — verify it.</span>}
            </li>
          ))}
        </ul>
      )}
      {r.insufficient_data && <p className="small muted">The records don't fully answer this.</p>}
      {nav && (
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => onGo(nav.tab, nav.section)}>
          {nav.tab === "report" && r.action?.changed ? "Open the AI report to review and save" : `Open ${TAB_NAMES[nav.tab]}`}
        </button>
      )}
      {r.follow_up_questions.length > 0 && (
        <div className="assistant-suggest">
          {r.follow_up_questions.map((q) => (
            <button key={q} type="button" className="assistant-chip" onClick={() => onAsk(q)}>
              {q}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
