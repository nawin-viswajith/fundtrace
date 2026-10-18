import { lazy, Suspense, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { createQueryClient } from "../api/queryClient";
import { AuthProvider, RequireAuth } from "../features/auth/AuthProvider";
import { ThemeProvider } from "../lib/theme";
import { ToastProvider } from "../components/Toast";
import { LoadingBlock, EmptyState } from "../components/Primitives";
import LoginPage from "../features/auth/LoginPage";
import AppShell from "../features/shell/AppShell";
import { RequireCustomer } from "../features/portal/parts";
import CaseQueue from "../features/queue/CaseQueue";
import OverviewPage from "../features/overview/OverviewPage";

const CaseWorkspace = lazy(() => import("../features/case/CaseWorkspace"));
const NetworkPage = lazy(() => import("../features/network/NetworkPage"));
const RulesPage = lazy(() => import("../features/rules/RulesPage"));
const OpsPage = lazy(() => import("../features/ops/OpsPage"));
const ReportPrint = lazy(() => import("../features/report/ReportPrint"));
const PortalShell = lazy(() => import("../features/portal/PortalShell"));
const PortalHome = lazy(() => import("../features/portal/PortalHome"));
const NewDisputePage = lazy(() => import("../features/portal/PortalHome").then((mod) => ({ default: mod.NewDisputePage })));
const DisputeForm = lazy(() => import("../features/portal/DisputeForm"));
const DisputeChat = lazy(() => import("../features/portal/DisputeChat"));
const DisputeDetail = lazy(() => import("../features/portal/DisputeDetail"));

function PageFallback() {
  return (
    <div className="page">
      <LoadingBlock label="Loading page" lines={6} />
    </div>
  );
}

function NotFound() {
  return (
    <div className="page">
      <EmptyState title="Page not found">The page you asked for does not exist.</EmptyState>
    </div>
  );
}

export default function App() {
  const [qc] = useState(createQueryClient);
  return (
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <ToastProvider>
          <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
            <AuthProvider>
              <Suspense fallback={<PageFallback />}>
                <Routes>
                  <Route path="/login" element={<LoginPage />} />
                  <Route
                    path="/portal"
                    element={
                      <RequireCustomer>
                        <PortalShell />
                      </RequireCustomer>
                    }
                  >
                    <Route index element={<PortalHome />} />
                    <Route path="new" element={<NewDisputePage />} />
                    <Route path="new/form" element={<DisputeForm />} />
                    <Route path="new/chat" element={<DisputeChat />} />
                    <Route path="disputes/:caseId" element={<DisputeDetail />} />
                  </Route>
                  <Route
                    path="/cases/:caseId/reports/:reportId/print"
                    element={
                      <RequireAuth>
                        <ReportPrint />
                      </RequireAuth>
                    }
                  />
                  <Route
                    element={
                      <RequireAuth>
                        <AppShell />
                      </RequireAuth>
                    }
                  >
                    <Route index element={<Navigate to="/overview" replace />} />
                    <Route path="/overview" element={<OverviewPage />} />
                    <Route path="/cases" element={<CaseQueue />} />
                    <Route
                      path="/cases/:caseId"
                      element={
                        <Suspense fallback={<PageFallback />}>
                          <CaseWorkspace />
                        </Suspense>
                      }
                    />
                    <Route path="/network" element={<NetworkPage />} />
                    <Route path="/rules" element={<RulesPage />} />
                    <Route path="/ops" element={<OpsPage />} />
                    <Route path="*" element={<NotFound />} />
                  </Route>
                </Routes>
              </Suspense>
            </AuthProvider>
          </BrowserRouter>
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
