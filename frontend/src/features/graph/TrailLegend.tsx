import type { Provenance } from "../../types/api";
import { PROVENANCE, PROVENANCE_ORDER } from "../../lib/labels";

/** How each kind of line looks, in words (never colour alone). */
const LINE_TEXT: Record<Provenance, { look: string; meaning: string }> = {
  confirmed: { look: "Solid green line", meaning: "a payment in the bank's records" },
  derived: { look: "Thin blue line", meaning: "worked out by the system from recorded payments" },
  inferred: { look: "Dashed amber line", meaning: "a possible link, not proven" },
  unknown: { look: "Dotted grey line", meaning: "not visible to this bank, or not checked yet" },
  contradictory: { look: "Red line", meaning: "two sources say different things" },
};

function Line({ color, width, dash }: { color: string; width: number; dash?: string }) {
  return (
    <svg width="34" height="10" aria-hidden="true" className="legend-line">
      <line x1="1" y1="5" x2="33" y2="5" stroke={color} strokeWidth={width} strokeDasharray={dash} strokeLinecap="round" />
    </svg>
  );
}

/** Plain legend for the money map. */
export function TrailLegend() {
  return (
    <section className="trail-legend" aria-labelledby="trail-legend-title">
      <h3 id="trail-legend-title" className="trail-legend-title">
        How to read the map
      </h3>
      <p className="small muted">Boxes with a name are accounts. Boxes with an amount are payments. Arrows show which way the money moved.</p>
      <ul className="trail-legend-list">
        {PROVENANCE_ORDER.map((p) => {
          const s = PROVENANCE[p];
          return (
            <li key={p}>
              <Line color={`var(--prov-${p})`} width={s.strokeWidth + 0.5} dash={s.dash} />
              <span>
                <strong>{LINE_TEXT[p].look}</strong> ({s.label}): {LINE_TEXT[p].meaning}
              </span>
            </li>
          );
        })}
        <li>
          <Line color="var(--prov-derived)" width={1.75} dash="6 5" />
          <span>
            <strong>Dashed blue line</strong> (between payments): some of the disputed money may have moved on from one payment to the next
          </span>
        </li>
        <li>
          <span className="legend-box legend-disputed" aria-hidden="true" />
          <span>
            <strong>Box with a thick dark border</strong>: the disputed payment
          </span>
        </li>
        <li>
          <span className="legend-box legend-muted" aria-hidden="true" />
          <span>
            <strong>Faded box, amount crossed out</strong>: a failed or reversed payment
          </span>
        </li>
        <li>
          <svg width="34" height="12" aria-hidden="true" className="legend-line">
            <line x1="1" y1="3" x2="33" y2="3" stroke="var(--prov-confirmed)" strokeWidth={1.5} />
            <line x1="1" y1="9" x2="33" y2="9" stroke="var(--prov-confirmed)" strokeWidth={4} />
          </svg>
          <span>Thicker lines mean larger amounts.</span>
        </li>
      </ul>
    </section>
  );
}
