import { useWorkspace } from "./workspace";
import { DimensionCards } from "./DimensionCards";
import { HoldsPanel } from "./HoldsPanel";
import { PlainPanel } from "./PlainPanel";
import { nextDeadline, nextSteps, whatHappened, whatIsMissing, whatWeFound, whereMoneyIs, type NextStep } from "./plainSummary";
import type { CaseSummary } from "../../types/api";

export function OverviewTab() {
  return (
    <div className="stack-lg plain-case">
      <CustomerStatement />
      <AtAGlance />
      <section className="plain-checks" aria-labelledby="case-checks-title">
        <h2 id="case-checks-title" className="h-section plain-h2">
          Six separate checks
        </h2>
        <p className="plain-lede">
          Each check looks at the case from one angle. They are kept separate on purpose: <strong>none of them is a verdict</strong>, and
          there is no combined score. You make the decision. Open a row to see the details.
        </p>
        <DimensionCards />
      </section>
      <HoldsPanel />
    </div>
  );
}

function CustomerStatement() {
  const { ctx } = useWorkspace();
  const c = ctx.case;
  const foreign = !!c.allegation_language && c.allegation_language !== "en";
  return (
    <PlainPanel
      id="case-statement"
      title="What the customer says"
      subtitle="In the customer's own words. We check it against the bank's records, so treat it as a statement to test, not a fact."
    >
      <figure className="fenced" aria-label="Customer's statement (not yet checked)">
        <figcaption className="fenced-label">
          Customer's words (not yet checked){foreign ? ` · language: ${c.allegation_language}` : ""}
        </figcaption>
        <blockquote className="fenced-text" lang={c.allegation_language || undefined}>
          {c.allegation}
        </blockquote>
      </figure>
      {c.allegation_translation && (
        <figure className="fenced fenced-ai" aria-label="AI translation">
          <figcaption className="fenced-label">AI translation — check it against the original</figcaption>
          <blockquote className="fenced-text" lang="en">
            {c.allegation_translation}
          </blockquote>
        </figure>
      )}
      {!c.allegation_translation && foreign && (
        <p className="muted small">No translation yet. Use “Suggest a category” at the top of the case to get one.</p>
      )}
      {c.intake && <CustomerAnswers channel={c.channel} intake={c.intake} />}
    </PlainPanel>
  );
}

function StepLink({ step }: { step: NextStep }) {
  const { setTab } = useWorkspace();
  if (!step.cta) return null;
  const go = () => {
    if (step.tab) setTab(step.tab);
    else if (step.anchor) {
      const el = document.getElementById(step.anchor);
      el?.scrollIntoView({ behavior: "smooth", block: "start" });
      el?.querySelector<HTMLElement>("h2")?.focus({ preventScroll: true });
    }
  };
  return (
    <button type="button" className="link-btn plain-step-link" onClick={go}>
      {step.cta}
    </button>
  );
}

function AtAGlance() {
  const { ctx } = useWorkspace();
  const money = whereMoneyIs(ctx);
  const missing = whatIsMissing(ctx);
  const steps = nextSteps(ctx);
  const deadline = nextDeadline(ctx);
  return (
    <PlainPanel id="case-glance" title="At a glance" subtitle="A plain summary of what the records show so far. The details are in the checks further down.">
      <dl className="glance">
        <div className="glance-row">
          <dt>What happened</dt>
          <dd>{whatHappened(ctx)}</dd>
        </div>
        <div className="glance-row">
          <dt>Where the money is now</dt>
          <dd>
            <ul className="glance-list">
              {money.map((s, i) => (
                <li key={i}>{s}</li>
              ))}
            </ul>
          </dd>
        </div>
        <div className="glance-row">
          <dt>Warning signs</dt>
          <dd>{whatWeFound(ctx)}</dd>
        </div>
        <div className="glance-row">
          <dt>What's missing</dt>
          <dd>
            {missing.length === 0 ? (
              "Nothing required is missing."
            ) : (
              <ul className="glance-list">
                {missing.map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ul>
            )}
          </dd>
        </div>
        {deadline && (
          <div className="glance-row">
            <dt>Next deadline</dt>
            <dd className={deadline.breached ? "bad-text strong" : undefined}>{deadline.text}</dd>
          </div>
        )}
        <div className="glance-row glance-next">
          <dt>What to do next</dt>
          <dd>
            <ol className="glance-steps">
              {steps.map((s, i) => (
                <li key={i}>
                  <span>{s.text}</span> <StepLink step={s} />
                </li>
              ))}
            </ol>
          </dd>
        </div>
      </dl>
    </PlainPanel>
  );
}

const OTP_TEXT: Record<string, string> = { yes: "Yes, shared one", no: "No", not_sure: "Not sure" };
const NOTICED_TEXT: Record<string, string> = { today: "The same day", yesterday: "The next day", "2_7_days": "2–7 days later", over_week: "More than a week later" };
const CONTACT_TEXT: Record<string, string> = { sms: "SMS", email: "Email", phone: "Phone call" };

/** What the customer answered when raising the dispute online — their own statements, not checked facts. */
function CustomerAnswers({ channel, intake }: { channel?: string; intake: NonNullable<CaseSummary["intake"]> }) {
  const via = channel === "portal_chat" ? "the guided chat" : channel === "portal_form" ? "the online form" : "the customer portal";
  return (
    <div className="customer-answers">
      <p className="small muted">Raised by the customer through {via}. Their answers:</p>
      <dl className="kv kv-tight">
        {intake.otp_shared && (
          <div className="kv-row">
            <dt>Shared an OTP, PIN or password</dt>
            <dd>{OTP_TEXT[intake.otp_shared] ?? intake.otp_shared}</dd>
          </div>
        )}
        {intake.noticed && (
          <div className="kv-row">
            <dt>Noticed</dt>
            <dd>{NOTICED_TEXT[intake.noticed] ?? intake.noticed}</dd>
          </div>
        )}
        <div className="kv-row">
          <dt>Cyber-crime complaint number</dt>
          <dd>{intake.cyber_complaint_ref || "Not given"}</dd>
        </div>
        {intake.contact_preference && (
          <div className="kv-row">
            <dt>Contact by</dt>
            <dd>{CONTACT_TEXT[intake.contact_preference] ?? intake.contact_preference}</dd>
          </div>
        )}
      </dl>
    </div>
  );
}
