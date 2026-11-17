import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router";
import type { Role } from "../api/types";
import { Spinner } from "../components/ui";
import { useAuth } from "./AuthContext";

/** Route guard. The backend enforces the same rules; this only keeps people off pages they cannot use. */
export function RequireRole({ roles, children }: { roles?: Role[]; children: ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <Spinner />;
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(location.pathname)}`} replace />;
  if (roles && !roles.includes(user.role)) return <Navigate to="/" replace />;
  return <>{children}</>;
}

export function homePathFor(role: Role): string {
  return role === "admin" ? "/admin/schemes" : role === "helper" ? "/citizens" : "/me/chat";
}
