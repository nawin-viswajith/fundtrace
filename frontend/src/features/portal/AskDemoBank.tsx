import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { ShieldAlert } from "lucide-react";
import { api } from "../../api/endpoints";
import { errorMessage } from "../../api/client";
import { LoadingBlock } from "../../components/Primitives";
import { usePortalHelpIndex, usePortalMe } from "../../api/hooks";
import type { HelpAction, HelpAnswer, HelpArticleBrief } from "../../types/api";
import { ChatAvatar } from "./parts";

interface Line {
  who: "bot" | "me";
  text: string;
  warning?: string | null;
  sourceLabel?: string;
  articles?: HelpArticleBrief[];
  actions?: HelpAction[];
  urgent?: boolean;
}

/** "Ask Demo Bank": a Gemini assistant scoped to banking, payments, fraud safety and this bank's disputes. */
export default function AskDemoBank() {
  const nav = useNavigate();
  const me = usePortalMe();
  const index = usePortalHelpIndex();
  const [lines, setLines] = useState<Line[]>([]);
  const [text, setText] = useState("");
  const listRef = useRef<HTMLDivElement>(null);
  const name = me.data?.name;

  const ask = useMutation({
    mutationFn: (question: string) => api.portalHelpAsk(question, historyFor(lines)),
    onMutate: (question) => setLines((prev) => [...prev, { who: "me", text: question }]),
    onSuccess: (a: HelpAnswer) => {
      setLines((prev) => [
        ...prev,
        { who: "bot", text: a.text, warning: a.warning, sourceLabel: a.source_label, articles: a.articles, actions: a.actions, urgent: a.urgent },
      ]);
    },
  });

  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [lines, ask.isPending]);

  const send = (q: string) => {
    const t = q.trim();
    if (!t || ask.isPending) return;
    ask.mutate(t);
    setText("");
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    send(text);
  };

  const doAction = (a: HelpAction) => {
    if (a.href.startsWith("/portal")) nav(a.href);
    else window.open(a.href, "_blank", "noopener,noreferrer");
  };

  return (
    <div className="portal-page">
      <header className="portal-hello">
        <p className="portal-kicker">Demo Bank · Help</p>
        <h1 className="portal-h1">Ask Demo Bank</h1>
        <p className="portal-lede">
          Ask about banking and payments, staying safe from fraud, or your own disputes. {index.data?.label ?? "Answers by AI (Gemini), from Demo Bank's help articles."}
        </p>
      </header>

      <section className="assist-shell" aria-label="Ask Demo Bank">
        <header className="assist-head">
          <ChatAvatar who="bot" />
          <span className="chat-head-title">
            <strong>Ask Demo Bank</strong>
            <span className="small">Answers by AI (Gemini), from Demo Bank's help articles</span>
          </span>
        </header>

        <div className="assist-list" ref={listRef} aria-live="polite" aria-label="Conversation">
          {lines.length === 0 && !ask.isPending && (
            <div className="assist-empty">
              <p>Try one of these, or type your own question below.</p>
            </div>
          )}
          {lines.map((l, i) => (
            <div key={i} className={`pmsg pmsg-${l.who} is-first`}>
              <ChatAvatar who={l.who} name={name} />
              <div className="assist-turn">
                <div className={`bubble bubble-${l.who} ${l.urgent ? "bubble-urgent" : ""}`}>
                  <span className="sr-only">{l.who === "bot" ? "Assistant: " : "You: "}</span>
                  {l.urgent && (
                    <span className="assist-urgent-flag">
                      <ShieldAlert size={16} aria-hidden="true" /> Act now
                    </span>
                  )}
                  {l.warning && (
                    <p className="assist-warning" role="alert">
                      {l.warning}
                    </p>
                  )}
                  <p>{l.text}</p>
                  {l.actions && l.actions.length > 0 && (
                    <div className="assist-actions">
                      {l.actions.map((a) => (
                        <button key={a.kind + a.href} type="button" className="btn btn-secondary assist-action" onClick={() => doAction(a)}>
                          {a.label}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                {l.who === "bot" && l.sourceLabel && (
                  <p className="assist-source small muted">
                    {l.sourceLabel}
                    {l.articles && l.articles.length > 0 && <> · {l.articles.map((a) => a.title).join(", ")}</>}
                  </p>
                )}
              </div>
            </div>
          ))}
          {ask.isPending && (
            <div className="pmsg pmsg-bot is-first">
              <ChatAvatar who="bot" />
              <div className="bubble bubble-bot bubble-typing" aria-label="Ask Demo Bank is answering">
                <span />
                <span />
                <span />
              </div>
            </div>
          )}
        </div>

        {index.isLoading ? (
          <LoadingBlock lines={2} />
        ) : (
          <div className="assist-chips" role="group" aria-label="Suggested questions">
            {(index.data?.suggestions ?? []).map((s) => (
              <button key={s} type="button" className="assist-chip" onClick={() => send(s)} disabled={ask.isPending}>
                {s}
              </button>
            ))}
          </div>
        )}

        <form className="chat-input assist-input" onSubmit={onSubmit}>
          <label className="sr-only" htmlFor="assist-text">
            Ask a question
          </label>
          <input
            id="assist-text"
            className="input"
            maxLength={1000}
            placeholder="e.g. How long does a dispute take?"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <button type="submit" className="btn btn-primary" disabled={text.trim().length < 2 || ask.isPending}>
            Ask
          </button>
        </form>
        {ask.error && (
          <p className="inline-error chat-error" role="alert">
            {errorMessage(ask.error)}
          </p>
        )}
      </section>
    </div>
  );
}

function historyFor(lines: Line[]): { role: string; text: string }[] {
  return lines.slice(-6).map((l) => ({ role: l.who === "me" ? "user" : "assistant", text: l.text }));
}
