import { useQuery } from "@tanstack/react-query";
import { createContext, useContext, type ReactNode } from "react";
import { api, ApiError } from "../api/client";
import { keys } from "../api/hooks";
import type { User } from "../api/types";

interface AuthState {
  user: User | null;
  loading: boolean;
}

const AuthContext = createContext<AuthState>({ user: null, loading: true });

async function fetchMe(): Promise<User | null> {
  try {
    return await api<User>("/auth/me");
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null;
    throw error;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const { data, isPending } = useQuery({ queryKey: keys.me, queryFn: fetchMe, retry: false });
  return <AuthContext.Provider value={{ user: data ?? null, loading: isPending }}>{children}</AuthContext.Provider>;
}

export const useAuth = () => useContext(AuthContext);
