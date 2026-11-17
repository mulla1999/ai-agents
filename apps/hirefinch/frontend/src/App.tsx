import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router";
import { api, setUnauthenticatedHandler } from "./api/client";
import type { AuthState } from "./api/types";
import { AuthContext, isAdmin } from "./auth";
import { Layout } from "./components/Layout";
import { Alert, Loading } from "./components/ui";
import { AccountPage } from "./pages/Account";
import { AdminAuditPage, AdminOverviewPage, AdminSettingsPage, AdminUsersPage } from "./pages/Admin";
import { AssistantPage } from "./pages/Assistant";
import { AuditPage } from "./pages/Audit";
import { ForgotPasswordPage, LoginPage, PrivacyPage, RegisterPage, ResetPasswordPage, VerifyEmailPage } from "./pages/AuthPages";
import { AutomationPage } from "./pages/Automation";
import { DashboardPage } from "./pages/Dashboard";
import { IntegrationsPage } from "./pages/Integrations";
import { JobDetailPage } from "./pages/JobDetail";
import { JobsPage } from "./pages/Jobs";
import { OutreachPage } from "./pages/Outreach";
import { ProfilePage } from "./pages/Profile";
import { QueuePage } from "./pages/Queue";
import { ResumeBuilderPage } from "./pages/ResumeBuilder";
import { ResumeStudioPage } from "./pages/ResumeStudio";
import { TrackerPage } from "./pages/Tracker";
import { BRAND } from "./brand";

// Pages that work whether or not you are signed in (links from emails land here).
const LINK_PAGES = (
  <>
    <Route path="verify-email" element={<VerifyEmailPage />} />
    <Route path="reset-password" element={<ResetPasswordPage />} />
    <Route path="privacy" element={<PrivacyPage />} />
  </>
);

export function App() {
  const client = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const auth = useQuery({ queryKey: ["auth"], queryFn: () => api<AuthState>("/auth/me") });
  const [expired, setExpired] = useState(false);

  useEffect(() => {
    setUnauthenticatedHandler(() => {
      setExpired(true);
      client.setQueryData(["auth"], { authenticated: false, user: null });
    });
  }, [client]);

  if (auth.isLoading) return <Loading label={`Connecting to ${BRAND}…`} />;
  if (auth.isError) {
    return (
      <div className="mx-auto mt-20 max-w-md p-4">
        <Alert tone="error">Cannot reach {BRAND} right now. ({(auth.error as Error).message})</Alert>
      </div>
    );
  }

  const user = auth.data?.authenticated ? auth.data.user : null;
  if (!user) {
    const signedIn = async () => {
      setExpired(false);
      await client.invalidateQueries({ queryKey: ["auth"] });
      const from = (location.state as { from?: string } | null)?.from;
      navigate(from && from !== "/login" ? from : "/", { replace: true });
    };
    return (
      <Routes>
        <Route path="login" element={<LoginPage onSignedIn={signedIn} expired={expired} />} />
        <Route path="register" element={<RegisterPage />} />
        <Route path="forgot-password" element={<ForgotPasswordPage />} />
        {LINK_PAGES}
        <Route path="*" element={<Navigate to="/login" replace state={{ from: location.pathname + location.search }} />} />
      </Routes>
    );
  }

  return (
    <AuthContext.Provider value={user}>
      <Routes>
        {LINK_PAGES}
        <Route path="login" element={<Navigate to="/" replace />} />
        <Route path="register" element={<Navigate to="/" replace />} />
        <Route path="forgot-password" element={<Navigate to="/account" replace />} />
        <Route
          path="*"
          element={
            <Layout user={user}>
              <Routes>
                <Route index element={<DashboardPage />} />
                <Route path="assistant" element={<AssistantPage />} />
                <Route path="jobs" element={<JobsPage />} />
                <Route path="jobs/:id" element={<JobDetailPage />} />
                <Route path="resume-builder" element={<ResumeBuilderPage />} />
                <Route path="resumes" element={<ResumeStudioPage />} />
                <Route path="resumes/:versionId" element={<ResumeStudioPage />} />
                <Route path="queue" element={<QueuePage />} />
                <Route path="tracker" element={<TrackerPage />} />
                <Route path="outreach" element={<OutreachPage />} />
                <Route path="profile" element={<ProfilePage />} />
                <Route path="integrations" element={<IntegrationsPage />} />
                <Route path="automation" element={<AutomationPage />} />
                <Route path="audit" element={<AuditPage />} />
                <Route path="account" element={<AccountPage />} />
                {isAdmin(user) && (
                  <>
                    <Route path="admin" element={<AdminOverviewPage />} />
                    <Route path="admin/users" element={<AdminUsersPage />} />
                    <Route path="admin/audit" element={<AdminAuditPage />} />
                    {user.role === "superadmin" && <Route path="admin/settings" element={<AdminSettingsPage />} />}
                  </>
                )}
                <Route path="*" element={<p className="text-sm text-slate-500">Page not found.</p>} />
              </Routes>
            </Layout>
          }
        />
      </Routes>
    </AuthContext.Provider>
  );
}
