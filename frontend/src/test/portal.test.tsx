import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { stepErrors } from "../features/portal/DisputeForm";
import DisputeChat from "../features/portal/DisputeChat";
import { AuthProvider, RequireAuth } from "../features/auth/AuthProvider";
import { api } from "../api/endpoints";
import type { ChatTurn, PortalPayment, PortalProfile } from "../types/api";

const profile: PortalProfile = {
  customer_id: "CUST-1002",
  name: "Kiran Shah",
  is_synthetic: true,
  accounts: [],
  reasons: [
    { key: "scam", label: "I was tricked into making this payment", help: "", asks_otp: true },
    { key: "charged_wrong", label: "I was charged twice or the wrong amount", help: "", asks_otp: false },
  ],
  options: { otp_shared: { no: "No" }, noticed: { today: "Today" }, contact_preference: { sms: "SMS" } },
};
const pay: PortalPayment = {
  id: "TXN-1",
  amount_minor: 150000,
  currency: "INR",
  amount: "₹1,500",
  paid_to: "Rahul K",
  paid_to_bank: null,
  channel: "UPI",
  reference: "6289",
  status: "posted",
  occurred_at: "2026-10-12T05:00:00Z",
  from_account: "ACC-1",
  dispute_case_id: null,
};
const base = { payment: pay, reason: "", otp_shared: "", noticed: "", cyber: "" as const, cyber_ref: "", description: "", contact: "", declaration: false };

describe("dispute form rules", () => {
  it("asks fraud-only questions only for fraud reasons, and needs every fixed choice", () => {
    expect(stepErrors(0, { ...base, payment: null }, profile)).toMatch(/Choose the payment/);
    expect(stepErrors(1, base, profile)).toMatch(/what happened/);
    const scam = { ...base, reason: "scam", noticed: "today", description: "Someone called me pretending to be the bank.", contact: "sms" };
    expect(stepErrors(2, scam, profile)).toMatch(/OTP/);
    expect(stepErrors(2, { ...scam, otp_shared: "no" }, profile)).toMatch(/cyber-crime/);
    expect(stepErrors(2, { ...scam, otp_shared: "no", cyber: "yes", cyber_ref: "<x>" }, profile)).toMatch(/complaint number/);
    expect(stepErrors(2, { ...scam, otp_shared: "no", cyber: "not_yet" }, profile)).toBeNull();
    const wrong = { ...base, reason: "charged_wrong", noticed: "today", description: "I was charged twice for one order.", contact: "sms" };
    expect(stepErrors(2, wrong, profile)).toBeNull(); // no OTP / cyber questions for a duplicate charge
    expect(stepErrors(2, { ...wrong, description: "too short" }, profile)).toMatch(/20 characters/);
    expect(stepErrors(3, wrong, profile)).toMatch(/declaration/);
  });
});

function turn(over: Partial<ChatTurn>): ChatTurn {
  return { state: {}, step: "payment", messages: [], options: [], payments: null, input: null, summary: null, ready: false, masked: [], ...over };
}

describe("guided dispute chat", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shows the customer's payments, and answers are choices, not free text", async () => {
    vi.spyOn(api, "portalMe").mockResolvedValue(profile);
    const chat = vi
      .spyOn(api, "portalChat")
      .mockResolvedValueOnce(turn({ messages: ["Hello Kiran.", "Which payment is this about?"], payments: [pay] }))
      .mockResolvedValueOnce(
        turn({ step: "reason", state: { txn_id: "TXN-1" }, messages: ["What happened with this payment?"], options: [{ value: "reason:scam", label: "I was tricked into making this payment" }] }),
      );
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <DisputeChat />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByText("Which payment is this about?")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument(); // no free text at this step
    await userEvent.click(screen.getByRole("button", { name: /₹1,500.*Rahul K/ }));
    expect(chat).toHaveBeenLastCalledWith({}, "txn:TXN-1", undefined); // the state from the previous answer goes back
    expect(await screen.findByRole("button", { name: /I was tricked/ })).toBeInTheDocument();
    expect(screen.getByText("₹1,500 to Rahul K")).toBeInTheDocument(); // the choice is echoed as the customer's reply
  });
});

describe("proof in the guided chat", () => {
  afterEach(() => vi.restoreAllMocks());

  const summary = {
    payment: pay,
    reason: "I was tricked into making this payment",
    otp_shared: "No",
    noticed: "Today",
    cyber_complaint: "Not reported yet",
    description: "Someone called pretending to be the bank.",
    contact_preference: "SMS",
  };
  const state = { txn_id: "TXN-1", reason: "scam", otp_shared: "no", noticed: "today", description: summary.description, contact_preference: "sms" };

  function renderChat() {
    return render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={["/portal/new/chat"]}>
          <Routes>
            <Route path="/portal/new/chat" element={<DisputeChat />} />
            <Route path="/portal/disputes/:caseId" element={<p>Dispute page</p>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }

  it("asks for proof before the summary, then sends the files once the dispute is raised", async () => {
    vi.spyOn(api, "portalMe").mockResolvedValue(profile);
    vi.spyOn(api, "portalChat").mockResolvedValue(
      turn({ step: "summary", state, summary, messages: ["Please check the details."], options: [{ value: "change:reason", label: "Change what happened" }], ready: true }),
    );
    const raise = vi.spyOn(api, "portalRaise").mockResolvedValue({ case_id: "CASE-9001", masked: [] } as never);
    const upload = vi.spyOn(api, "portalUpload").mockResolvedValue({} as never);
    renderChat();
    const u = userEvent.setup();
    expect(await screen.findByText(/do you have any proof/)).toBeInTheDocument();
    expect(screen.queryByText("Check your dispute")).not.toBeInTheDocument(); // the summary waits for the proof answer
    const file = new File(["receipt"], "upi-receipt.png", { type: "image/png" });
    await u.upload(screen.getByLabelText("Add files"), file);
    expect(screen.getByText("upi-receipt.png")).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: /Continue with 1 file/ }));
    expect(screen.getByText("I've added 1 file.")).toBeInTheDocument();
    expect(screen.getByText("Check your dispute")).toBeInTheDocument();
    expect(screen.getByText("1 file to send")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Change what happened" })).toBeInTheDocument(); // edits sit inside the card
    await u.click(screen.getByRole("checkbox"));
    await u.click(screen.getByRole("button", { name: "Submit dispute" }));
    expect(await screen.findByText("Dispute page")).toBeInTheDocument();
    expect(raise).toHaveBeenCalledWith(expect.objectContaining({ txn_id: "TXN-1", channel: "portal_chat" }));
    expect(upload).toHaveBeenCalledWith("CASE-9001", file, "customer_evidence");
  });

  it("lets the customer skip proof, and refuses files that are too big or the wrong type", async () => {
    vi.spyOn(api, "portalMe").mockResolvedValue(profile);
    vi.spyOn(api, "portalChat").mockResolvedValue(turn({ step: "summary", state, summary, messages: ["Please check the details."], ready: true }));
    renderChat();
    const u = userEvent.setup({ applyAccept: false });
    await screen.findByText(/do you have any proof/);
    const big = new File(["x"], "huge.png", { type: "image/png" });
    Object.defineProperty(big, "size", { value: 6 * 1024 * 1024 });
    await u.upload(screen.getByLabelText("Add files"), big);
    expect(screen.getByRole("alert")).toHaveTextContent("larger than 5 MB");
    await u.upload(screen.getByLabelText("Add files"), new File(["x"], "tool.exe", { type: "application/octet-stream" }));
    expect(screen.getByRole("alert")).toHaveTextContent("not a photo, PDF or text file");
    await u.click(screen.getByRole("button", { name: "I don't have any" }));
    expect(screen.getByText("None added")).toBeInTheDocument();
  });
});

describe("bank customers stay in the portal", () => {
  afterEach(() => vi.restoreAllMocks());

  it("redirects a customer login away from the bank's dispute screens", async () => {
    vi.spyOn(api, "me").mockResolvedValue({ user: { id: 7, username: "cust.kiran", full_name: "Kiran Shah", role: "customer" } });
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={["/overview"]}>
          <AuthProvider>
            <Routes>
              <Route path="/overview" element={<RequireAuth><p>Bank overview</p></RequireAuth>} />
              <Route path="/portal" element={<p>Customer portal</p>} />
            </Routes>
          </AuthProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByText("Customer portal")).toBeInTheDocument();
    expect(screen.queryByText("Bank overview")).not.toBeInTheDocument();
  });
});
