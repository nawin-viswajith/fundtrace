import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { DlpLine, EvidenceScorePanel, ScoreBadge } from "../features/evidence/EvidenceScore";
import { AuthProvider } from "../features/auth/AuthProvider";
import LoginPage from "../features/auth/LoginPage";
import { ThemeProvider } from "../lib/theme";
import { api } from "../api/endpoints";
import { ApiError } from "../api/client";
import type { EvidenceScore } from "../types/api";

const score: EvidenceScore = {
  version: "evidence-score-v1",
  overall: 40,
  uncapped: 71,
  band: "weak",
  caps: [{ cap: 40, reason: "At least one printed value contradicts the ledger" }],
  note: "Evidence strength, not customer credibility or fraud likelihood.",
  categories: [
    { key: "ledger_match", label: "Ledger match", weight: 30, score: 43, basis: "code", about: "", reasons: ["Amount contradicts the ledger: document ₹45,000.00, ledger ₹50,000.00."] },
    { key: "integrity", label: "Integrity", weight: 25, score: 100, basis: "AI observations, scored by code", about: "", reasons: ["No signs of editing."] },
    { key: "relevance", label: "Relevance", weight: 15, score: null, basis: "AI label, scored by code", about: "", reasons: ["Not assessed."] },
  ],
};

describe("evidence strength", () => {
  it("shows the overall score, the cap and every category with its weight", () => {
    render(<EvidenceScorePanel score={score} />);
    const region = screen.getByRole("region", { name: "Evidence strength" });
    expect(within(region).getByText(/Held down to 40 \(it would be 71\)/)).toBeInTheDocument();
    expect(screen.getByRole("meter", { name: "Ledger match 43 of 100" })).toHaveAttribute("aria-valuenow", "43");
    expect(screen.getByRole("meter", { name: "Integrity 100 of 100" })).toBeInTheDocument();
    expect(screen.getByText("Not assessed")).toBeInTheDocument();
    expect(screen.getByText("30%")).toBeInTheDocument();
    expect(screen.getByText(/Amount contradicts the ledger/)).toBeInTheDocument(); // inside "Why these scores"
  });

  it("badge names the band", () => {
    render(<ScoreBadge score={score} />);
    expect(screen.getByText("Weak")).toBeInTheDocument();
    expect(screen.getByText("40")).toBeInTheDocument();
  });

  it("DLP line lists types and counts, never values, and flags restricted data", () => {
    render(
      <DlpLine
        dlp={{
          backend: "local",
          status: "scanned",
          findings: [
            { type: "CREDIT_CARD_NUMBER", label: "Card number", count: 2, likelihood: "VERY_LIKELY", masked_in_notes: true },
            { type: "EMAIL_ADDRESS", label: "Email address", count: 1, likelihood: "LIKELY", masked_in_notes: false },
          ],
        }}
      />,
    );
    expect(screen.getByText(/Contains restricted data/)).toBeInTheDocument();
    expect(screen.getByText(/Card number ×2, Email address\./)).toBeInTheDocument();
  });
});

function renderLogin() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <ThemeProvider>
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/login"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <AuthProvider>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/overview" element={<p>Overview page</p>} />
            </Routes>
          </AuthProvider>
        </MemoryRouter>
      </QueryClientProvider>
    </ThemeProvider>,
  );
}

const cfg = { demo: true, demo_users: [], demo_password: null, firebase_enabled: false, firebase: null, synthetic_data: true };
const user = { id: 9, username: "sup.meera", full_name: "Meera", role: "supervisor" as const, mfa_enabled: true, mfa_required: false };

describe("sign-in with MFA", () => {
  afterEach(() => vi.restoreAllMocks());

  it("asks for the authenticator code after the password, then opens the session", async () => {
    vi.spyOn(api, "me").mockRejectedValue(new ApiError(401, "unauthenticated", "Not authenticated"));
    vi.spyOn(api, "authConfig").mockResolvedValue(cfg);
    vi.spyOn(api, "login").mockResolvedValue({ mfa_required: true, mfa_token: "pending-token-123456" });
    const verify = vi.spyOn(api, "mfaVerify").mockResolvedValue({ user, recovery_codes_left: null });
    renderLogin();
    const u = userEvent.setup();
    await u.type(await screen.findByLabelText("Username"), "sup.meera");
    await u.type(screen.getByLabelText("Password"), "pw");
    await u.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Two-step verification" })).toBeInTheDocument();
    const verifyBtn = screen.getByRole("button", { name: "Verify" });
    expect(verifyBtn).toBeDisabled();
    await u.type(screen.getByLabelText(/6-digit code/), "123456");
    await u.click(verifyBtn);
    expect(verify).toHaveBeenCalledWith("pending-token-123456", "123456");
    expect(await screen.findByText("Overview page")).toBeInTheDocument();
  });

  it("offers a recovery code instead", async () => {
    vi.spyOn(api, "me").mockRejectedValue(new ApiError(401, "unauthenticated", "Not authenticated"));
    vi.spyOn(api, "authConfig").mockResolvedValue(cfg);
    vi.spyOn(api, "login").mockResolvedValue({ mfa_required: true, mfa_token: "pending-token-123456" });
    vi.spyOn(api, "mfaVerify").mockRejectedValue(new ApiError(401, "unauthenticated", "That code is not valid."));
    renderLogin();
    const u = userEvent.setup();
    await u.type(await screen.findByLabelText("Username"), "sup.meera");
    await u.type(screen.getByLabelText("Password"), "pw");
    await u.click(screen.getByRole("button", { name: "Sign in" }));
    await u.click(await screen.findByRole("button", { name: /Use a recovery code/ }));
    await u.type(screen.getByLabelText("Recovery code"), "abcde-12345");
    await u.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByText("That code is not valid.")).toBeInTheDocument();
  });
});
