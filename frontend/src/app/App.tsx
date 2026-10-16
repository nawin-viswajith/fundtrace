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
import CaseQueue from "../features/queue/CaseQueue";

const CaseWorkspace = lazy(() => import("../features/case/CaseWorkspace"));
const NetworkPage = lazy(() => import("../features/network/NetworkPage"));
const RulesPage = lazy(() => import("../features/rules/RulesPage"));
const OpsPage = lazy(() => import("../features/ops/OpsPage"));
const ReportPrint = lazy(() => import("../features/report/ReportPrint"));

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
                    <Route index element={<Navigate to="/cases" replace />} />
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
