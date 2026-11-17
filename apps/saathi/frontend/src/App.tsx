import { Navigate, Route, Routes } from "react-router";
import { useAuth } from "./auth/AuthContext";
import { AccountPage } from "./auth/AccountPage";
import { LoginPage } from "./auth/LoginPage";
import { homePathFor, RequireRole } from "./auth/RequireRole";
import { Layout } from "./components/Layout";
import { Spinner } from "./components/ui";
import { SchemeEditor } from "./features/admin/SchemeEditor";
import { SchemesPage } from "./features/admin/SchemesPage";
import { StatsPage } from "./features/admin/StatsPage";
import { UsersPage } from "./features/admin/UsersPage";
import { CitizenWorkspace } from "./features/citizen/CitizenWorkspace";
import { CitizensPage } from "./features/helper/CitizensPage";

function Home() {
  const { user, loading } = useAuth();
  if (loading) return <Spinner />;
  return <Navigate to={user ? homePathFor(user.role) : "/login"} replace />;
}

export function App() {
  return (
    <Routes>
      <Route path="login" element={<LoginPage />} />
      <Route path="register" element={<LoginPage mode="register" />} />
      <Route element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="account" element={<RequireRole><AccountPage /></RequireRole>} />
        <Route path="me/*" element={<RequireRole><CitizenWorkspace /></RequireRole>} />
        <Route path="citizens" element={<RequireRole roles={["helper", "admin"]}><CitizensPage /></RequireRole>} />
        <Route path="citizens/:citizenId/*" element={<RequireRole roles={["helper", "admin"]}><CitizenWorkspace /></RequireRole>} />
        <Route path="admin/schemes" element={<RequireRole roles={["admin"]}><SchemesPage /></RequireRole>} />
        <Route path="admin/schemes/new" element={<RequireRole roles={["admin"]}><SchemeEditor /></RequireRole>} />
        <Route path="admin/schemes/:schemeId" element={<RequireRole roles={["admin"]}><SchemeEditor /></RequireRole>} />
        <Route path="admin/users" element={<RequireRole roles={["admin"]}><UsersPage /></RequireRole>} />
        <Route path="admin/stats" element={<RequireRole roles={["admin"]}><StatsPage /></RequireRole>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
