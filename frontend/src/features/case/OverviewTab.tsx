import { useWorkspace } from "./workspace";
import { DimensionCards } from "./DimensionCards";
import { HoldsPanel } from "./HoldsPanel";
import { PlainPanel } from "./PlainPanel";
import { nextDeadline, nextSteps, whatHappened, whatIsMissing, whatWeFound, whereMoneyIs, type NextStep } from "./plainSummary";

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
        <p className="muted small">No translation yet. You can ask the AI for one on the AI report tab.</p>
      )}
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
