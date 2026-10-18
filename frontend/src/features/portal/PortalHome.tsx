import { Link } from "react-router-dom";
import { ArrowRight, Bot, CheckCircle2, ClipboardList, MessageCircleQuestion, ShieldAlert } from "lucide-react";
import { usePortalDisputes, usePortalMe, usePortalSafetyCheck } from "../../api/hooks";
import type { PortalDisputeBrief } from "../../types/api";
import { EmptyState, ErrorState, LoadingBlock, Time } from "../../components/Primitives";
import { firstName } from "./parts";

const STEPS = 4; // Received → Being investigated → Final review → Decided

/** Customer home: raise a new dispute (chatbot or form), then follow the ones already raised. */
export default function PortalHome() {
  const me = usePortalMe();
  const list = usePortalDisputes();
  const disputes = list.data?.disputes ?? [];
  return (
    <div className="portal-page">
      <header className="portal-hello is-hero">
        <p className="portal-kicker">Demo Bank · Help with a payment</p>
        <h1 className="portal-h1">{me.data ? `Hello ${firstName(me.data.name)}` : "Hello"}</h1>
        <p className="portal-lede">Something wrong with a payment from your account? Tell us and we'll look into it.</p>
      </header>

      <section className="portal-section" aria-labelledby="raise">
        <div className="portal-section-head">
          <h2 id="raise" className="portal-h2">
            Raise a dispute
          </h2>
          <p className="small muted">Both ways ask the same questions. Nothing is sent until you check it and press Submit.</p>
        </div>
        <NewDisputeChoices />
        <AskDemoBankCard />
      </section>

      <section className="portal-section" aria-labelledby="safety">
        <div className="portal-section-head">
          <h2 id="safety" className="portal-h2">
            Your safety check
          </h2>
        </div>
        <SafetyPanel />
      </section>

      <section className="portal-section" aria-labelledby="my-disputes">
        <div className="portal-section-head">
          <h2 id="my-disputes" className="portal-h2">
            My disputes{disputes.length ? <span className="portal-count">{disputes.length}</span> : null}
          </h2>
        </div>
        {list.isLoading ? (
          <LoadingBlock lines={3} />
        ) : list.error ? (
          <ErrorState error={list.error} onRetry={() => list.refetch()} />
        ) : !disputes.length ? (
          <EmptyState title="You haven't raised any disputes">When you do, you can follow them here.</EmptyState>
        ) : (
          <ul className="dispute-list">
            {disputes.map((d) => (
              <DisputeRow key={d.case_id} d={d} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function DisputeRow({ d }: { d: PortalDisputeBrief }) {
  return (
    <li>
      <Link to={`/portal/disputes/${d.case_id}`} className="dispute-row">
        <span className="dispute-row-main">
          <strong>
            {d.payment.amount} to {d.payment.paid_to}
          </strong>
          <span className="small muted">
            {d.reason} · raised <Time iso={d.raised_at} dateOnly /> · reference {d.case_id}
          </span>
        </span>
        <span className="dispute-progress">
          <span className={`dispute-status step-${d.step}`}>
            {d.needs_action > 0 && <span className="dispute-action">Action needed</span>}
            {d.status}
          </span>
          <span className="progress-bar" aria-hidden="true">
            {Array.from({ length: STEPS }, (_, i) => (
              <span key={i} className={i < d.step ? "is-on" : ""} />
            ))}
          </span>
          <span className="small muted">
            Step {Math.min(d.step, STEPS)} of {STEPS}
          </span>
        </span>
        <ArrowRight size={18} className="dispute-go" aria-hidden="true" />
      </Link>
    </li>
  );
}

export function NewDisputeChoices() {
  return (
    <div className="raise-panel" role="group" aria-label="How would you like to raise a dispute?">
      <Link to="/portal/new/chat" className="raise-opt">
        <span className="raise-icon" aria-hidden="true">
          <Bot size={24} />
        </span>
        <span className="raise-body">
          <span className="raise-title">
            Chat with our assistant <span className="raise-tag">Interactive</span>
          </span>
          <span className="raise-text">A chatbot asks one question at a time and you tap an answer. About two minutes.</span>
        </span>
        <span className="raise-cta">
          Start chat <ArrowRight size={16} aria-hidden="true" />
        </span>
      </Link>
      <Link to="/portal/new/form" className="raise-opt">
        <span className="raise-icon" aria-hidden="true">
          <ClipboardList size={24} />
        </span>
        <span className="raise-body">
          <span className="raise-title">Fill in a form</span>
          <span className="raise-text">Four short steps. Good if you'd like to see every question before you answer.</span>
        </span>
        <span className="raise-cta">
          Open form <ArrowRight size={16} aria-hidden="true" />
        </span>
      </Link>
    </div>
  );
}

function SafetyPanel() {
  const check = usePortalSafetyCheck();
  if (check.isLoading) return <LoadingBlock lines={2} />;
  if (check.error) return <ErrorState error={check.error} onRetry={() => check.refetch()} />;
  const data = check.data;
  if (!data) return null;
  const tip = data.tips[data.tip_index];
  return (
    <div className="safety-grid">
      <div className="portal-card safety-card">
        {data.all_clear ? (
          <p className="safety-clear">
            <CheckCircle2 size={20} aria-hidden="true" /> {data.all_clear_text}
          </p>
        ) : (
          <ul className="safety-items">
            {data.items.map((it, i) => (
              <li key={i} className="safety-item">
                <ShieldAlert size={18} aria-hidden="true" className="safety-item-icon" />
                <span>
                  <strong>{it.title}</strong>
                  <span className="small muted safety-item-text">{it.text}</span>
                  {it.action && (
                    <Link to={it.action.href.startsWith("/portal") ? it.action.href : "#"} className="link-btn small">
                      {it.action.label}
                    </Link>
                  )}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
      {tip && (
        <div className="portal-card portal-card-action safety-tip">
          <p className="portal-kicker">Scam to watch for</p>
          <strong>{tip.title}</strong>
          <p className="small muted">{tip.summary}</p>
          <Link to="/portal/help" className="link-btn small">
            Learn more in Ask Demo Bank
          </Link>
        </div>
      )}
    </div>
  );
}

export function AskDemoBankCard() {
  return (
    <Link to="/portal/help" className="assist-entry">
      <span className="assist-entry-icon" aria-hidden="true">
        <MessageCircleQuestion size={22} />
      </span>
      <span className="assist-entry-body">
        <span className="assist-entry-title">
          Ask Demo Bank <span className="raise-tag">AI</span>
        </span>
        <span className="small muted">FAQs, fraud safety tips, and the status of your own disputes — answered by Gemini.</span>
      </span>
      <ArrowRight size={16} aria-hidden="true" className="assist-entry-go" />
    </Link>
  );
}

export function NewDisputePage() {
  return (
    <div className="portal-page">
      <h1 className="portal-h1">Raise a dispute</h1>
      <p className="portal-lede">Choose how you'd like to tell us. Both ask the same questions, and nothing is sent until you confirm.</p>
      <NewDisputeChoices />
    </div>
  );
}
