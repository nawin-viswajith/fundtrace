import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ProvenanceChip, RuleStatusChip } from "../components/Chip";
import { ProvenanceLegend } from "../components/Domain";
import { PROVENANCE, provenanceStyle, ruleStatusInfo } from "../lib/labels";

describe("provenance mapping", () => {
  it("maps every label to a distinct line style", () => {
    expect(PROVENANCE.confirmed.dash).toBeUndefined();
    expect(PROVENANCE.derived.dash).toBeUndefined();
    expect(PROVENANCE.derived.strokeWidth).toBeLessThan(PROVENANCE.confirmed.strokeWidth);
    expect(PROVENANCE.inferred.dash).toBe("7 5");
    expect(PROVENANCE.unknown.dash).toBe("2 4");
    expect(PROVENANCE.contradictory.tone).toBe("contradictory");
  });
  it("tolerates snapshot strings like 'confirmed (ledger record)' and unknown values", () => {
    expect(provenanceStyle("confirmed (ledger record)").label).toBe("Recorded");
    expect(provenanceStyle("INFERRED").label).toBe("Possible link");
    expect(provenanceStyle("something-else").label).toBe("Not known");
    expect(provenanceStyle(null).label).toBe("Not known");
  });
  it("renders a chip with plain-language meaning", () => {
    render(<ProvenanceChip provenance="inferred" showMeaning />);
    const chip = screen.getByText("Possible link").closest(".chip");
    expect(chip).toHaveClass("chip-prov-inferred");
    expect(chip).toHaveAttribute("title", "Possible link: Possible, but not proven (inferred)");
    expect(screen.getByText(/Possible, but not proven/)).toBeInTheDocument();
  });
  it("legend lists all five labels in plain words", () => {
    render(<ProvenanceLegend />);
    for (const l of ["Recorded:", "Calculated:", "Possible link:", "Not known:", "Records disagree:"]) expect(screen.getByText(l)).toBeInTheDocument();
    expect(screen.getByText("a payment in the bank's records (confirmed)")).toBeInTheDocument();
    expect(screen.getByText("possible, but not proven (inferred)")).toBeInTheDocument();
  });
});

describe("rule status chip", () => {
  it("never shows 'not evaluable' as clear — it says data missing", () => {
    render(<RuleStatusChip status="not_evaluable" />);
    const chip = screen.getByText("Can't check — data missing");
    expect(chip).toHaveClass("chip-rule-missing");
    expect(chip.getAttribute("title")).toMatch(/not a negative finding/);
    expect(chip.textContent).not.toMatch(/clear/i);
  });
  it("distinguishes triggered and not triggered", () => {
    render(
      <>
        <RuleStatusChip status="triggered" />
        <RuleStatusChip status="not_triggered" />
      </>,
    );
    expect(screen.getByText("Found")).toHaveClass("chip-rule-triggered");
    expect(screen.getByText("Not found")).toHaveClass("chip-rule-clear");
    expect(ruleStatusInfo("weird").label).toBe("weird");
  });
});
