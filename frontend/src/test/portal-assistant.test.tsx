import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import AskDemoBank from "../features/portal/AskDemoBank";
import DisputeChat from "../features/portal/DisputeChat";
import { api } from "../api/endpoints";
import type { ChatTurn, HelpAnswer, HelpIndex, PortalPayment, PortalProfile } from "../types/api";

const profile: PortalProfile = {
  customer_id: "CUST-1002",
  name: "Kiran Shah",
  is_synthetic: true,
  accounts: [],
  reasons: [{ key: "scam", label: "I was tricked into making this payment", help: "", asks_otp: true }],
  options: { otp_shared: { no: "No" }, noticed: { today: "Today" }, contact_preference: { sms: "SMS" } },
};

function turn(over: Partial<ChatTurn>): ChatTurn {
  return { state: {}, step: "payment", messages: [], options: [], payments: null, input: null, summary: null, ready: false, masked: [], ...over };
}

function renderWithProviders(ui: React.ReactElement) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Ask Demo Bank", () => {
  afterEach(() => vi.restoreAllMocks());

  const index: HelpIndex = {
    articles: [{ id: "DSP-HOW", title: "How to raise a dispute", summary: "", topic: "dispute" }],
    suggestions: ["How long does a dispute take?", "What proof should I send?"],
    label: "Answers by AI (Gemini), from Demo Bank's help articles",
  };

  it("shows suggested questions and renders a cited answer with its source label", async () => {
    vi.spyOn(api, "portalMe").mockResolvedValue(profile);
    vi.spyOn(api, "portalHelpIndex").mockResolvedValue(index);
    const ask = vi.spyOn(api, "portalHelpAsk").mockResolvedValue({
      status: "ok",
      source: "ai",
      source_label: "Answer by AI (Gemini), from Demo Bank's help articles",
      intent: "faq",
      text: "Raise it from your recent payments in the app.",
      warning: null,
      urgent: false,
      masked_message: null,
      articles: [{ id: "DSP-HOW", title: "How to raise a dispute", summary: "", topic: "dispute" }],
      disputes: [],
      actions: [],
      suggestions: [],
    } satisfies HelpAnswer);

    renderWithProviders(<AskDemoBank />);
    const chip = await screen.findByRole("button", { name: "How long does a dispute take?" });
    await userEvent.click(chip);
    expect(ask).toHaveBeenCalledWith("How long does a dispute take?", [{ role: "user", text: "How long does a dispute take?" }]);
    expect(await screen.findByText("Raise it from your recent payments in the app.")).toBeInTheDocument();
    expect(screen.getByText(/Answer by AI \(Gemini\)/)).toBeInTheDocument();
    expect(screen.getByText(/How to raise a dispute/)).toBeInTheDocument();
  });

  it("shows a warning banner and urgent flag for an unsafe or urgent message", async () => {
    vi.spyOn(api, "portalMe").mockResolvedValue(profile);
    vi.spyOn(api, "portalHelpIndex").mockResolvedValue(index);
    vi.spyOn(api, "portalHelpAsk").mockResolvedValue({
      status: "ok",
      source: "ai",
      source_label: "Answer by AI (Gemini), from Demo Bank's help articles",
      intent: "urgent_fraud_now",
      text: "Call 1930 right away and block your card.",
      warning: "For your safety I've hidden what looked like an OTP.",
      urgent: true,
      masked_message: "I just shared [REDACTED]",
      articles: [{ id: "SAFE-FIRST-HOUR", title: "Lost money to fraud just now? Do this first", summary: "", topic: "safety" }],
      disputes: [],
      actions: [{ kind: "call_1930", label: "Call 1930 (cyber-crime helpline)", href: "tel:1930" }],
      suggestions: [],
    } satisfies HelpAnswer);

    renderWithProviders(<AskDemoBank />);
    const input = await screen.findByPlaceholderText(/how long does a dispute take/i);
    await userEvent.type(input, "I just shared my OTP with someone");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText("Call 1930 right away and block your card.")).toBeInTheDocument();
    expect(screen.getByText(/hidden what looked like an OTP/)).toBeInTheDocument();
    expect(screen.getByText("Act now")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Call 1930 (cyber-crime helpline)" })).toBeInTheDocument();
  });

  it("shows a plain refusal for an out-of-scope question", async () => {
    vi.spyOn(api, "portalMe").mockResolvedValue(profile);
    vi.spyOn(api, "portalHelpIndex").mockResolvedValue(index);
    vi.spyOn(api, "portalHelpAsk").mockResolvedValue({
      status: "refused",
      source: "policy",
      source_label: "Demo Bank assistant",
      intent: "out_of_scope",
      text: "I can only help with banking and payments, staying safe from fraud and scams, and disputes with Demo Bank.",
      warning: null,
      urgent: false,
      masked_message: null,
      articles: [],
      disputes: [],
      actions: [],
      suggestions: ["How long does a dispute take?"],
    } satisfies HelpAnswer);

    renderWithProviders(<AskDemoBank />);
    const input = await screen.findByPlaceholderText(/how long does a dispute take/i);
    await userEvent.type(input, "What's a good biryani recipe?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText(/I can only help with banking/)).toBeInTheDocument();
  });
});

describe("pre-filling the guided chat from a free-text story", () => {
  afterEach(() => vi.restoreAllMocks());

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

  function renderChat() {
    return render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={["/portal/new/chat"]}>
          <Routes>
            <Route path="/portal/new/chat" element={<DisputeChat />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }

  it("offers 'tell us in your own words', then every suggestion needs a Yes/No before it counts", async () => {
    vi.spyOn(api, "portalMe").mockResolvedValue(profile);
    vi.spyOn(api, "portalChat").mockResolvedValueOnce(
      turn({ messages: ["Hello Kiran.", "Which payment is this about?"], payments: [pay], options: [{ value: "story", label: "Tell us in your own words instead" }] }),
    );
    const story = vi.spyOn(api, "portalChatStory").mockResolvedValue(
      turn({
        step: "confirm_payment",
        state: { payment_candidate: "TXN-1", suggest: { reason: "scam" } },
        messages: ["Thanks.", "From what you told us, we think this might be the payment — is that right?"],
        payments: [pay],
        options: [
          { value: "confirmyes:payment", label: "Yes, that's the one" },
          { value: "confirmno:payment", label: "No, let me choose" },
        ],
      }),
    );
    const chat = vi.spyOn(api, "portalChat").mockResolvedValueOnce(
      turn({
        step: "confirm_reason",
        state: { txn_id: "TXN-1", suggest: { reason: "scam" } },
        messages: ["It sounds like what happened was: “I was tricked into making this payment” — is that right?"],
        options: [
          { value: "confirmyes:reason", label: "Yes, that's right" },
          { value: "confirmno:reason", label: "No, let me choose" },
        ],
      }),
    );

    renderChat();
    await screen.findByText("Which payment is this about?");
    await userEvent.click(screen.getByRole("button", { name: "Tell us in your own words instead" }));
    const box = await screen.findByPlaceholderText(/I got a call from someone/);
    await userEvent.type(box, "Someone called pretending to be from my bank and tricked me into paying them.");
    await userEvent.click(screen.getByRole("button", { name: /Tell us/ }));
    expect(story).toHaveBeenCalledWith(expect.stringContaining("Someone called pretending"));
    expect(await screen.findByText(/we think this might be the payment/)).toBeInTheDocument();
    // the candidate payment is shown, but not as a selectable button (it needs explicit confirmation)
    expect(screen.queryByRole("button", { name: /₹1,500.*Rahul K/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Yes, that's the one" }));
    await waitFor(() => expect(chat).toHaveBeenCalledWith({ payment_candidate: "TXN-1", suggest: { reason: "scam" } }, "confirmyes:payment", undefined));
    expect(await screen.findByText(/It sounds like what happened was/)).toBeInTheDocument();
  });

  it("lets the customer go back to the step-by-step questions instead of telling a story", async () => {
    vi.spyOn(api, "portalMe").mockResolvedValue(profile);
    vi.spyOn(api, "portalChat").mockResolvedValue(
      turn({ messages: ["Hello Kiran.", "Which payment is this about?"], payments: [pay], options: [{ value: "story", label: "Tell us in your own words instead" }] }),
    );
    renderChat();
    await screen.findByText("Which payment is this about?");
    await userEvent.click(screen.getByRole("button", { name: "Tell us in your own words instead" }));
    await screen.findByPlaceholderText(/I got a call from someone/);
    await userEvent.click(screen.getByRole("button", { name: "Back to the questions" }));
    expect(screen.queryByPlaceholderText(/I got a call from someone/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /₹1,500.*Rahul K/ })).toBeInTheDocument();
  });
});
