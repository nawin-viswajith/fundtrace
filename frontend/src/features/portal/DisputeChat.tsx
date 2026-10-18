import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/endpoints";
import { errorMessage } from "../../api/client";
import { InlineError, LoadingBlock } from "../../components/Primitives";
import type { ChatTurn } from "../../types/api";
import { PaymentCard } from "./parts";

interface Line {
  who: "bot" | "me";
  text: string;
}

/** Guided dispute chat: one question at a time, answered with buttons (text only where the step asks for it). */
export default function DisputeChat() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const [lines, setLines] = useState<Line[]>([]);
  const [turn, setTurn] = useState<ChatTurn | null>(null);
  const [text, setText] = useState("");
  const [declared, setDeclared] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const started = useRef(false);

  const step = useMutation({
    mutationFn: (v: { choice?: string; text?: string; said?: string }) => api.portalChat(turn?.state ?? null, v.choice, v.text),
    onMutate: (v) => {
      setErr(null);
      if (v.said) setLines((prev) => [...prev, { who: "me", text: v.said! }]);
    },
    onSuccess: (t) => {
      setTurn(t);
      setLines((prev) => {
        // If an OTP, PIN or card number was hidden, show the customer's message the way it was saved.
        const echo = t.masked.length && t.state.description && prev.length && prev[prev.length - 1].who === "me"
          ? [...prev.slice(0, -1), { who: "me" as const, text: t.state.description }]
          : prev;
        return [...echo, ...t.messages.map((m) => ({ who: "bot" as const, text: m }))];
      });
      setText("");
    },
    onError: (e) => setErr(errorMessage(e)),
  });

  const submit = useMutation({
    mutationFn: () => {
      const s = turn!.state;
      return api.portalRaise({
        txn_id: s.txn_id!,
        reason: s.reason!,
        description: s.description!,
        otp_shared: s.otp_shared ?? null,
        noticed: s.noticed!,
        cyber_complaint_ref: s.cyber_complaint_ref || null,
        contact_preference: s.contact_preference!,
        declaration: declared,
        channel: "portal_chat",
      });
    },
    onSuccess: async (d) => {
      await qc.invalidateQueries({ queryKey: ["portal"] });
      nav(`/portal/disputes/${d.case_id}`, { state: { justRaised: true, masked: d.masked ?? [] } });
    },
  });

  useEffect(() => {
    if (started.current) return; // start once (React strict mode mounts twice)
    started.current = true;
    step.mutate({});
  }, [step]);
  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [lines, turn]);

  const onText = (e: FormEvent) => {
    e.preventDefault();
    const t = text.trim();
    if (!t || !turn?.input) return;
    step.mutate({ text: t, said: t });
  };

  return (
    <div className="portal-page">
      <h1 className="portal-h1">Raise a dispute</h1>
      <p className="portal-lede">Chat with our assistant and tap an answer to each question. Nothing is sent until you check the summary and press Submit.</p>
      <section className="portal-card chat" aria-label="Dispute assistant">
        <div className="chat-list" ref={listRef} aria-live="polite">
          {lines.map((l, i) => (
            <div key={i} className={`bubble bubble-${l.who}`}>
              {l.text}
            </div>
          ))}
          {step.isPending && <div className="bubble bubble-bot bubble-typing">…</div>}
          {!turn && !step.isPending && !err && <LoadingBlock lines={2} />}
        </div>

        {turn && !step.isPending && (
          <div className="chat-answer">
            {turn.payments && turn.payments.length > 0 && (
              <div className="pay-list" role="list" aria-label="Your recent payments">
                {turn.payments.map((p) => (
                  <div role="listitem" key={p.id}>
                    <PaymentCard p={p} onSelect={() => step.mutate({ choice: `txn:${p.id}`, said: `${p.amount} to ${p.paid_to}` })} />
                  </div>
                ))}
              </div>
            )}

            {turn.summary && (
              <div className="chat-summary">
                <dl className="review-list">
                  <div>
                    <dt>Payment</dt>
                    <dd>
                      <PaymentCard p={turn.summary.payment} />
                    </dd>
                  </div>
                  <div>
                    <dt>What happened</dt>
                    <dd>{turn.summary.reason}</dd>
                  </div>
                  {turn.summary.otp_shared && (
                    <div>
                      <dt>Shared an OTP, PIN or password</dt>
                      <dd>{turn.summary.otp_shared}</dd>
                    </div>
                  )}
                  <div>
                    <dt>Noticed</dt>
                    <dd>{turn.summary.noticed}</dd>
                  </div>
                  {turn.summary.cyber_complaint && (
                    <div>
                      <dt>Cyber-crime complaint</dt>
                      <dd>{turn.summary.cyber_complaint}</dd>
                    </div>
                  )}
                  <div>
                    <dt>Your description</dt>
                    <dd className="review-text">{turn.summary.description}</dd>
                  </div>
                  <div>
                    <dt>Contact me by</dt>
                    <dd>{turn.summary.contact_preference}</dd>
                  </div>
                </dl>
                <label className="declaration">
                  <input type="checkbox" checked={declared} onChange={(e) => setDeclared(e.target.checked)} />
                  <span>The information I have given is true to the best of my knowledge. I understand the bank will look at its records of this payment.</span>
                </label>
                <button type="button" className="btn btn-primary" disabled={!declared || submit.isPending} onClick={() => submit.mutate()}>
                  {submit.isPending ? "Sending…" : "Submit dispute"}
                </button>
                <InlineError error={submit.error} />
              </div>
            )}

            {turn.options.length > 0 && (
              <div className="chat-options" role="group" aria-label="Choose an answer">
                {turn.options.map((o) => (
                  <button key={o.value} type="button" className="chat-option" onClick={() => step.mutate({ choice: o.value, said: o.label })}>
                    <span className="choice-label">{o.label}</span>
                    {o.help && <span className="choice-help">{o.help}</span>}
                  </button>
                ))}
              </div>
            )}

            {turn.input && (
              <form className="chat-input" onSubmit={onText}>
                <label className="sr-only" htmlFor="chat-text">
                  Your answer
                </label>
                {turn.input.kind === "description" ? (
                  <textarea
                    id="chat-text"
                    className="textarea"
                    rows={4}
                    maxLength={turn.input.max}
                    placeholder={turn.input.placeholder}
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                  />
                ) : (
                  <input
                    id="chat-text"
                    className="input"
                    maxLength={turn.input.max}
                    placeholder={turn.input.placeholder}
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                  />
                )}
                <button type="submit" className="btn btn-primary" disabled={text.trim().length < (turn.input.kind === "description" ? 1 : 4)}>
                  Send
                </button>
              </form>
            )}
          </div>
        )}
        {err && (
          <p className="inline-error" role="alert">
            {err}
          </p>
        )}
      </section>
    </div>
  );
}
