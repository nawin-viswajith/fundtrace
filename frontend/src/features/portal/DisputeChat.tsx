import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Send } from "lucide-react";
import { api } from "../../api/endpoints";
import { errorMessage } from "../../api/client";
import { InlineError, LoadingBlock } from "../../components/Primitives";
import { usePortalMe } from "../../api/hooks";
import type { ChatTurn } from "../../types/api";
import { ChatAvatar, DisputeSummaryCard, PaymentCard, ProofPicker, sendProof, type PendingProof } from "./parts";

interface Line {
  who: "bot" | "me";
  text: string;
}

// Where each server step sits in the conversation (the proof question belongs to the last one).
const STAGE: Record<string, number> = { payment: 1, reason: 2, otp: 3, noticed: 3, cyber: 4, cyber_ref: 4, description: 5, contact: 6, summary: 7 };
const STAGES = 7;
const PROOF_QUESTION =
  "One more thing: do you have any proof? A screenshot of the payment, the bank's SMS, a receipt or your complaint acknowledgement helps us check much faster. You can skip this and send files later.";

/** Guided dispute chat: one question at a time, answered with buttons (text only where the step asks for it). */
export default function DisputeChat() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const me = usePortalMe();
  const [lines, setLines] = useState<Line[]>([]);
  const [turn, setTurn] = useState<ChatTurn | null>(null);
  const [text, setText] = useState("");
  const [declared, setDeclared] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [proof, setProof] = useState<PendingProof[]>([]);
  const [proofAsked, setProofAsked] = useState(false); // the assistant has asked for proof
  const [proofDone, setProofDone] = useState(false); // the customer has answered it
  const [tellingStory, setTellingStory] = useState(false); // showing the free-text "in your own words" box
  const [story, setStory] = useState("");
  const held = useRef<string[]>([]); // the summary's own messages, shown after the proof question
  const listRef = useRef<HTMLDivElement>(null);
  const started = useRef(false);
  const name = me.data?.name;

  const step = useMutation({
    mutationFn: (v: { choice?: string; text?: string; said?: string; story?: string }) =>
      v.story !== undefined ? api.portalChatStory(v.story) : api.portalChat(turn?.state ?? null, v.choice, v.text),
    onMutate: (v) => {
      setErr(null);
      if (v.said) setLines((prev) => [...prev, { who: "me", text: v.said! }]);
    },
    onSuccess: (t) => {
      setTurn(t);
      const askProof = !!t.summary && !proofAsked;
      if (askProof) {
        held.current = t.messages;
        setProofAsked(true);
      }
      setLines((prev) => {
        // If an OTP, PIN or card number was hidden, show the customer's message the way it was saved.
        const echo =
          t.masked.length && t.state.description && prev.length && prev[prev.length - 1].who === "me"
            ? [...prev.slice(0, -1), { who: "me" as const, text: t.state.description }]
            : prev;
        const said = askProof ? [PROOF_QUESTION] : t.messages;
        return [...echo, ...said.map((m) => ({ who: "bot" as const, text: m }))];
      });
      setText("");
      setTellingStory(false);
      setStory("");
    },
    onError: (e) => setErr(errorMessage(e)),
  });

  const finishProof = () => {
    const said = proof.length ? `I've added ${proof.length} file${proof.length === 1 ? "" : "s"}.` : "I don't have any proof to add.";
    const next = held.current.length ? held.current : ["Please check the details. If everything is right, confirm the declaration and submit."];
    held.current = [];
    setLines((prev) => [...prev, { who: "me", text: said }, ...next.map((m) => ({ who: "bot" as const, text: m }))]);
    setProofDone(true);
  };

  const submit = useMutation({
    mutationFn: async () => {
      const s = turn!.state;
      const d = await api.portalRaise({
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
      const failed = await sendProof(d.case_id, proof, api.portalUpload);
      return { d, failed };
    },
    onSuccess: async ({ d, failed }) => {
      await qc.invalidateQueries({ queryKey: ["portal"] });
      nav(`/portal/disputes/${d.case_id}`, { state: { justRaised: true, masked: d.masked ?? [], filesSent: proof.length - failed, filesFailed: failed } });
    },
  });

  useEffect(() => {
    if (started.current) return; // start once (React strict mode mounts twice)
    started.current = true;
    step.mutate({});
  }, [step]);
  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [lines, turn, proofDone]);

  const onText = (e: FormEvent) => {
    e.preventDefault();
    const t = text.trim();
    if (!t || !turn?.input) return;
    step.mutate({ text: t, said: t });
  };

  const change = (slot: string) => {
    const o = turn?.options.find((x) => x.value === `change:${slot}`);
    return o ? () => step.mutate({ choice: o.value, said: o.label }) : undefined;
  };
  const stage = turn ? (STAGE[turn.step] ?? 1) : 0;
  const inSummary = !!turn?.summary;
  const showProof = inSummary && !proofDone;
  const showSummary = inSummary && proofDone;
  const isConfirmStep = !!turn?.step.startsWith("confirm_"); // an AI-suggested answer waiting for Yes / No
  const sendStory = (e: FormEvent) => {
    e.preventDefault();
    const t = story.trim();
    if (!t) return;
    step.mutate({ story: t, said: t });
  };

  return (
    <div className="portal-page">
      <header className="portal-hello">
        <p className="portal-kicker">Raise a dispute</p>
        <h1 className="portal-h1">Chat with our assistant</h1>
        <p className="portal-lede">Tap an answer to each question. Nothing is sent until you check the summary and press Submit.</p>
      </header>
      <section className="chat-shell" aria-label="Dispute assistant">
        <header className="chat-head">
          <ChatAvatar who="bot" />
          <span className="chat-head-title">
            <strong>Demo Bank assistant</strong>
            <span className="small">Guided questions · usually 2 minutes</span>
          </span>
          <span className="chat-progress" aria-label={inSummary ? "Final check" : `Question ${stage} of ${STAGES - 1}`}>
            <span className="chat-progress-label">{inSummary ? "Final check" : stage ? `Question ${stage} of ${STAGES - 1}` : "Starting"}</span>
            <span className="chat-progress-bar" aria-hidden="true">
              <span style={{ width: `${(Math.max(stage, 0) / STAGES) * 100}%` }} />
            </span>
          </span>
        </header>

        <div className="chat-list" ref={listRef} aria-live="polite">
          {lines.map((l, i) => {
            const first = i === 0 || lines[i - 1].who !== l.who;
            return (
              <div key={i} className={`pmsg pmsg-${l.who} ${first ? "is-first" : ""}`}>
                {first ? <ChatAvatar who={l.who} name={name} /> : <span className="pavatar-gap" aria-hidden="true" />}
                <div className={`bubble bubble-${l.who}`}>
                  {first && <span className="sr-only">{l.who === "bot" ? "Assistant: " : "You: "}</span>}
                  {l.text}
                </div>
              </div>
            );
          })}
          {step.isPending && (
            <div className="pmsg pmsg-bot is-first">
              <ChatAvatar who="bot" />
              <div className="bubble bubble-bot bubble-typing" aria-label="The assistant is typing">
                <span />
                <span />
                <span />
              </div>
            </div>
          )}
          {!turn && !step.isPending && !err && <LoadingBlock lines={2} />}
        </div>

        {turn && !step.isPending && tellingStory && turn.step === "payment" && (
          <div className="chat-answer">
            <form className="chat-input story-input" onSubmit={sendStory}>
              <label className="sr-only" htmlFor="story-text">
                Tell us what happened, in your own words
              </label>
              <textarea
                id="story-text"
                className="textarea"
                rows={4}
                maxLength={2000}
                placeholder="e.g. I got a call from someone saying they were from the bank and asking me to pay to keep my account safe…"
                value={story}
                onChange={(e) => setStory(e.target.value)}
                autoFocus
              />
              <div className="chat-proof-actions">
                <button type="submit" className="btn btn-primary" disabled={story.trim().length < 20 || step.isPending}>
                  <Send size={16} aria-hidden="true" /> Tell us
                </button>
                <button type="button" className="btn btn-secondary" onClick={() => setTellingStory(false)}>
                  Back to the questions
                </button>
              </div>
              <p className="small muted">At least 20 characters. Please don't include OTPs, PINs, passwords or full card numbers.</p>
            </form>
          </div>
        )}

        {turn && !step.isPending && !tellingStory && (
          <div className="chat-answer">
            {turn.payments && turn.payments.length > 0 && (
              <div className="pay-list" role="list" aria-label="Your recent payments">
                {turn.payments.map((p) => (
                  <div role="listitem" key={p.id}>
                    {isConfirmStep ? (
                      <PaymentCard p={p} />
                    ) : (
                      <PaymentCard p={p} onSelect={() => step.mutate({ choice: `txn:${p.id}`, said: `${p.amount} to ${p.paid_to}` })} />
                    )}
                  </div>
                ))}
              </div>
            )}

            {showProof && (
              <div className="chat-proof">
                <ProofPicker files={proof} onChange={setProof} />
                <div className="chat-proof-actions">
                  <button type="button" className="btn btn-primary" onClick={finishProof} disabled={!proof.length}>
                    Continue with {proof.length || "these"} file{proof.length === 1 ? "" : "s"}
                  </button>
                  <button type="button" className="btn btn-secondary" onClick={finishProof} disabled={proof.length > 0}>
                    I don't have any
                  </button>
                </div>
              </div>
            )}

            {showSummary && turn.summary && (
              <div className="chat-summary">
                <DisputeSummaryCard
                  payment={turn.summary.payment}
                  onChangePayment={change("txn_id")}
                  description={turn.summary.description}
                  onChangeDescription={change("description")}
                  items={[
                    { label: "What happened", value: turn.summary.reason, onChange: change("reason") },
                    ...(turn.summary.otp_shared ? [{ label: "Shared an OTP, PIN or password", value: turn.summary.otp_shared }] : []),
                    { label: "Noticed", value: turn.summary.noticed },
                    ...(turn.summary.cyber_complaint ? [{ label: "Cyber-crime complaint", value: turn.summary.cyber_complaint }] : []),
                    { label: "Contact me by", value: turn.summary.contact_preference, onChange: change("contact_preference") },
                    {
                      label: "Proof",
                      value: proof.length ? `${proof.length} file${proof.length === 1 ? "" : "s"} to send` : "None added",
                      onChange: () => setProofDone(false),
                    },
                  ]}
                />
                <label className="declaration">
                  <input type="checkbox" checked={declared} onChange={(e) => setDeclared(e.target.checked)} />
                  <span>The information I have given is true to the best of my knowledge. I understand the bank will look at its records of this payment.</span>
                </label>
                <button type="button" className="btn btn-primary btn-block" disabled={!declared || submit.isPending} onClick={() => submit.mutate()}>
                  {submit.isPending ? (proof.length ? "Sending your dispute and files…" : "Sending…") : "Submit dispute"}
                </button>
                <InlineError error={submit.error} />
              </div>
            )}

            {!inSummary && turn.options.length > 0 && (
              <div className="chat-options" role="group" aria-label="Choose an answer">
                {turn.options
                  .filter((o) => o.value !== "story")
                  .map((o) => (
                    <button key={o.value} type="button" className="chat-option" onClick={() => step.mutate({ choice: o.value, said: o.label })}>
                      <span className="choice-label">{o.label}</span>
                      {o.help && <span className="choice-help">{o.help}</span>}
                    </button>
                  ))}
              </div>
            )}

            {turn.step === "payment" && turn.options.some((o) => o.value === "story") && (
              <button type="button" className="link-btn small story-toggle" onClick={() => setTellingStory(true)}>
                Tell us in your own words instead
              </button>
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
                    rows={3}
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
                  <Send size={16} aria-hidden="true" /> Send
                </button>
              </form>
            )}
          </div>
        )}
        {err && (
          <p className="inline-error chat-error" role="alert">
            {err}
          </p>
        )}
      </section>
    </div>
  );
}
