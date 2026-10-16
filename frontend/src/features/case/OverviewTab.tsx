import { Languages, Quote } from "lucide-react";
import { useWorkspace } from "./workspace";
import { DimensionCards } from "./DimensionCards";
import { HoldsPanel } from "./HoldsPanel";
import { Card } from "../../components/Primitives";

export function OverviewTab() {
  const { ctx } = useWorkspace();
  const c = ctx.case;
  return (
    <div className="stack-lg">
      <Card title="Customer statement" subtitle="What the customer told us. It is a claim to test, not a fact.">
        <figure className="fenced" aria-label="Customer-provided statement (unverified)">
          <figcaption className="fenced-label">
            <Quote size={13} aria-hidden="true" /> Customer-provided (unverified){c.allegation_language !== "en" ? ` · language: ${c.allegation_language}` : ""}
          </figcaption>
          <blockquote className="fenced-text" lang={c.allegation_language || undefined}>
            {c.allegation}
          </blockquote>
        </figure>
        {c.allegation_translation && (
          <figure className="fenced fenced-ai" aria-label="AI translation">
            <figcaption className="fenced-label">
              <Languages size={13} aria-hidden="true" /> AI translation (Gemini) — check against the original
            </figcaption>
            <blockquote className="fenced-text" lang="en">
              {c.allegation_translation}
            </blockquote>
          </figure>
        )}
        {!c.allegation_translation && c.allegation_language !== "en" && (
          <p className="muted small">No translation yet. Use “AI category suggestion” on the AI report tab to request one.</p>
        )}
      </Card>

      <div>
        <h2 className="h-section">Assessment dimensions</h2>
        <DimensionCards />
        <p className="footnote">
          These dimensions are shown separately on purpose; none of them is a verdict. There is no combined trust score.
        </p>
      </div>

      <HoldsPanel />
    </div>
  );
}
