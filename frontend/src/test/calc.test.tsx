import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import type { Attribution, CaseContext } from "../types/api";
import type { CalcRecord, CalcVerifyResult } from "../features/calc/api";

// The calc API module is mocked: the component is tested against fixed records and spies.
const state = vi.hoisted(() => ({
  record: undefined as unknown,
  verifyData: undefined as unknown,
  verifyMutate: vi.fn(),
  downloadMutate: vi.fn(),
  recordArgs: [] as unknown[],
}));

vi.mock("../features/calc/api", async (importOriginal) => {
  const orig = await importOriginal<typeof import("../features/calc/api")>();
  return {
    ...orig,
    useCalcRecord: (caseId: string | undefined, p: unknown) => {
      state.recordArgs = [caseId, p];
      return { data: caseId ? state.record : undefined, isLoading: false, error: null };
    },
    useVerifyCalc: () => ({ mutate: state.verifyMutate, data: state.verifyData, isPending: false, error: null }),
    useDownloadCalc: () => ({ mutate: state.downloadMutate, isPending: false, isSuccess: false, error: null }),
  };
});

import { CalcRecordSection, SourceRangeNote, sameFigures } from "../features/calc/CalcRecordSection";
import { AttributionPanel } from "../features/graph/AttributionPanel";
import { WorkspaceCtx, type WorkspaceApi } from "../features/case/workspace";

const FP = "ab12cd34".repeat(8);
const buckets = {
  residual_in_visible_accounts: 0,
  left_visibility: 0,
  reached_merchant_or_hub: 999900,
  returned_to_payer: 0,
  beyond_trace_limits: 0,
  unaccounted: 0,
};

const att = {
  disputed_txn_id: "TXN-1",
  disputed_amount_minor: 999900,
  currency: "INR",
  methods: { min: "Lower", fifo: "FIFO", pro_rata: "Pro-rata", max: "Upper" },
  per_transaction: {},
  per_account: {},
  buckets: { min: buckets, fifo: buckets, pro_rata: buckets, max: buckets },
  coverage: { min: 1, fifo: 1, pro_rata: 1, max: 1 },
  warnings: [],
  caveat: "",
  evaluable: true,
  exits: {},
  holdable: [],
} as unknown as Attribution;

function makeRecord(over: Partial<CalcRecord> = {}): CalcRecord {
  return {
    record_type: "fundtrace.calculation_record",
    calc_version: "1.0",
    case_id: "CASE-24045",
    disputed_txn_id: "TXN-1",
    currency: "INR",
    generated_at: "2026-10-18T10:00:00Z",
    versions: { calc_version: "1.0", attribution_version: "1.0", method_versions: { min: "1.0", fifo: "1.0", pro_rata: "1.0", max: "1.0" } },
    methods: [
      { id: "min", name: "Clean money spent first", label: "Lower bound", version: "1.0", bound: "lower", definition: "Clean money leaves first.", formula: "x" },
      { id: "fifo", name: "First in, first out", label: "FIFO", version: "1.0", bound: "estimate", definition: "Oldest money first.", formula: "x" },
      { id: "pro_rata", name: "Proportional mix", label: "Pro-rata", version: "1.0", bound: "estimate", definition: "Same mix.", formula: "x" },
      { id: "max", name: "Disputed money spent first", label: "Upper bound", version: "1.0", bound: "upper", definition: "Disputed first.", formula: "x" },
    ],
    method_symbols: "",
    assumptions: [{ id: "commingling", text: "Money in an account is mixed." }],
    kinds: { inputs: "Observed.", outputs: "Calculated.", conclusions: "None." },
    inputs: {
      trace_parameters: {
        direction: "both",
        attribution_direction: "both",
        depth: 3,
        window_hours: 72,
        max_nodes: 150,
        hub_threshold: 25,
        per_account_cap: 40,
        expand_accounts: [],
        window_start: "2026-10-16T10:00:00Z",
        window_end: "2026-10-19T10:00:00Z",
        activity_limit: 500,
      },
      accounts: [],
      trail_txn_ids: ["TXN-1"],
      transactions: [],
      opening_balances: [],
      fingerprint: { algorithm: "SHA-256", value: FP, covers: "Everything used.", canonical_form: "JSON" },
    },
    outputs: { disputed_amount_minor: 999900, evaluable: true, buckets: att.buckets, fingerprint: { algorithm: "SHA-256", value: "f".repeat(64) } },
    amount_ranges: [
      {
        txn_id: "TXN-1",
        role: "disputed",
        currency: "INR",
        min_minor: 999000,
        max_minor: 999900,
        used_minor: 999900,
        used_system: "core",
        used_system_label: "core banking",
        reported: [
          { system: "core", system_label: "core banking", record_id: "cbs-1", amount_minor: 999900 },
          { system: "upi_switch", system_label: "UPI switch", record_id: "npci-sw-80931", amount_minor: 999000 },
        ],
        statement: "₹9,990 ≤ amount ≤ ₹9,999",
        explanation: "",
      },
    ],
    primary_record_rule: "",
    checks: [
      { id: "conservation", name: "Every rupee of the disputed payment is accounted for", what_it_checks: "", status: "pass", detail: "Adds up exactly.", items: [] },
      {
        id: "source_agreement",
        name: "The bank's systems agree on each payment",
        what_it_checks: "",
        status: "warn",
        detail: "The bank's systems disagree on at least one payment.",
        items: [{ status: "warn", text: "TXN-1: core banking ₹9,999; UPI switch ₹9,990." }],
      },
      { id: "bounds_order", name: "Lowest and highest figures are in the right order", what_it_checks: "", status: "not_applicable", detail: "No onward payments.", items: [] },
    ],
    checks_summary: { pass: 1, warn: 1, fail: 0, not_applicable: 1, overall: "warn" },
    ...over,
  };
}

function withWs(children: ReactNode) {
  const ws: WorkspaceApi = {
    caseId: "CASE-24045",
    ctx: { graph: { params: { depth: 3, window_hours: 72 } } } as unknown as CaseContext,
    setTab: vi.fn(),
    showOnGraph: vi.fn(),
    highlight: [],
    clearHighlight: vi.fn(),
  };
  return <WorkspaceCtx.Provider value={ws}>{children}</WorkspaceCtx.Provider>;
}

beforeEach(() => {
  state.record = makeRecord();
  state.verifyData = undefined;
  state.verifyMutate.mockReset();
  state.downloadMutate.mockReset();
});

describe("calculation record section", () => {
  it("is collapsed and summarises the checks in its heading", () => {
    const { container } = render(<CalcRecordSection caseId="CASE-24045" params={{}} att={att} record={makeRecord()} loading={false} error={null} />);
    const details = container.querySelector("details.calc-record");
    expect(details).not.toHaveAttribute("open");
    expect(screen.getByText("How these figures were calculated")).toBeInTheDocument();
    expect(screen.getByText(/1 check to look at/)).toBeInTheDocument();
  });

  it("shows methods with versions, checks in words (not colour alone) and the fingerprint", () => {
    render(<CalcRecordSection caseId="CASE-24045" params={{}} att={att} record={makeRecord()} loading={false} error={null} />);
    expect(screen.getByText("Clean money spent first")).toBeInTheDocument();
    expect(screen.getAllByText("(version 1.0)")).toHaveLength(4);
    const checks = screen.getByRole("list", { name: "Checks on the arithmetic" });
    expect(within(checks).getByText("Passed")).toBeInTheDocument();
    expect(within(checks).getByText("Check this")).toBeInTheDocument();
    expect(within(checks).getByText("Not applicable")).toBeInTheDocument();
    expect(within(checks).getByText(/core banking ₹9,999; UPI switch ₹9,990/)).toBeInTheDocument();
    expect(screen.getByTestId("calc-fingerprint")).toHaveTextContent(FP);
    expect(screen.queryByText(/use different settings/)).not.toBeInTheDocument();
  });

  it("checks the result again with the record's fingerprint and reports a match", async () => {
    const { rerender } = render(<CalcRecordSection caseId="CASE-24045" params={{}} att={att} record={makeRecord()} loading={false} error={null} />);
    await userEvent.click(screen.getByRole("button", { name: "Check it gives the same result" }));
    expect(state.verifyMutate).toHaveBeenCalledWith(FP);
    state.verifyData = { matches: true, fingerprint: FP, output_fingerprint: "f", expected_fingerprint: FP, calc_version: "1.0", differences: [], checked_at: "2026-10-18T10:00:00Z" } satisfies CalcVerifyResult;
    rerender(<CalcRecordSection caseId="CASE-24045" params={{}} att={att} record={makeRecord()} loading={false} error={null} />);
    expect(screen.getByText(/Same result\./)).toBeInTheDocument();
  });

  it("lists the differences when the result cannot be reproduced", () => {
    state.verifyData = {
      matches: false,
      fingerprint: "1".repeat(64),
      output_fingerprint: "f",
      expected_fingerprint: FP,
      calc_version: "1.0",
      differences: ["The bank's records have changed since your copy was made."],
      checked_at: "2026-10-18T10:00:00Z",
    } satisfies CalcVerifyResult;
    render(<CalcRecordSection caseId="CASE-24045" params={{}} att={att} record={makeRecord()} loading={false} error={null} />);
    expect(screen.getByText(/Different result/)).toBeInTheDocument();
    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByText(/records have changed since your copy/)).toBeInTheDocument();
  });

  it("downloads the record", async () => {
    render(<CalcRecordSection caseId="CASE-24045" params={{}} att={att} record={makeRecord()} loading={false} error={null} />);
    await userEvent.click(screen.getByRole("button", { name: "Download calculation record (JSON)" }));
    expect(state.downloadMutate).toHaveBeenCalledTimes(1);
  });

  it("warns when the record was worked out with other settings than the figures shown", () => {
    const other = makeRecord({ outputs: { ...makeRecord().outputs, disputed_amount_minor: 1 } });
    expect(sameFigures(other, att)).toBe(false);
    render(<CalcRecordSection caseId="CASE-24045" params={{}} att={att} record={other} loading={false} error={null} />);
    expect(screen.getByText(/use different settings/)).toBeInTheDocument();
  });
});

describe("source disagreement range (§7.6)", () => {
  it("states the range, who reported what, and which amount the figures use", () => {
    render(<SourceRangeNote ranges={makeRecord().amount_ranges} />);
    const note = screen.getByRole("note");
    expect(note).toHaveTextContent("The bank's systems disagree on this payment: ₹9,990–₹9,999.");
    expect(note).toHaveTextContent("Figures below use the core banking amount ₹9,999");
    expect(note).toHaveTextContent("UPI switch: ₹9,990");
  });

  it("renders nothing when the systems agree", () => {
    const { container } = render(<SourceRangeNote ranges={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("money panel", () => {
  it("shows the range note and the calculation section inside a case", () => {
    render(withWs(<AttributionPanel att={att} paths={[]} nodes={new Map()} onSelect={vi.fn()} />));
    expect(screen.getByRole("note")).toHaveTextContent("₹9,990–₹9,999");
    expect(screen.getByText("How these figures were calculated")).toBeInTheDocument();
    expect(state.recordArgs).toEqual(["CASE-24045", { direction: "both", depth: 3, window_hours: 72 }]);
  });

  it("omits the calculation record outside a case workspace", () => {
    render(<AttributionPanel att={att} paths={[]} nodes={new Map()} onSelect={vi.fn()} />);
    expect(screen.queryByText("How these figures were calculated")).not.toBeInTheDocument();
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });
});
