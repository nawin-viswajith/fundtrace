import { Link } from "react-router-dom";
import { MessageCircle, ClipboardList } from "lucide-react";
import { usePortalDisputes, usePortalMe } from "../../api/hooks";
import { EmptyState, ErrorState, LoadingBlock, Time } from "../../components/Primitives";
import { firstName } from "./parts";

/** Customer home: their disputes, and the two ways to raise a new one. */
export default function PortalHome() {
  const me = usePortalMe();
  const list = usePortalDisputes();
  return (
    <div className="portal-page">
      <h1 className="portal-h1">{me.data ? `Hello ${firstName(me.data.name)}` : "Hello"}</h1>
      <p className="portal-lede">Something wrong with a payment from your account? Tell us and we'll look into it.</p>
      <NewDisputeChoices />

      <section className="portal-section" aria-labelledby="my-disputes">
        <h2 id="my-disputes" className="portal-h2">
          My disputes
        </h2>
        {list.isLoading ? (
          <LoadingBlock lines={3} />
        ) : list.error ? (
          <ErrorState error={list.error} onRetry={() => list.refetch()} />
        ) : !list.data?.disputes.length ? (
          <EmptyState title="You haven't raised any disputes">When you do, you can follow them here.</EmptyState>
        ) : (
          <ul className="dispute-list">
            {list.data.disputes.map((d) => (
              <li key={d.case_id}>
                <Link to={`/portal/disputes/${d.case_id}`} className="dispute-row">
                  <span className="dispute-row-main">
                    <strong>
                      {d.payment.amount} to {d.payment.paid_to}
                    </strong>
                    <span className="small muted">
                      {d.reason} · raised <Time iso={d.raised_at} dateOnly /> · reference {d.case_id}
                    </span>
                  </span>
                  <span className={`dispute-status step-${d.step}`}>{d.status}</span>
                  {d.needs_action > 0 && <span className="dispute-action">Action needed</span>}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

export function NewDisputeChoices() {
  return (
    <div className="choice-grid" role="group" aria-label="How would you like to raise a dispute?">
      <Link to="/portal/new/chat" className="choice-card">
        <MessageCircle size={28} aria-hidden="true" />
        <strong>Answer a few questions</strong>
        <span>Our assistant asks you one question at a time. Takes about two minutes.</span>
      </Link>
      <Link to="/portal/new/form" className="choice-card">
        <ClipboardList size={28} aria-hidden="true" />
        <strong>Fill in a form</strong>
        <span>See all the questions on one page, step by step.</span>
      </Link>
    </div>
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
