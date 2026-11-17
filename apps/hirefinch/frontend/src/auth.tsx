// The signed-in user, available to every page.

import { createContext, useContext } from "react";
import type { User } from "./api/types";

export const AuthContext = createContext<User | null>(null);

export function useMe(): User {
  const user = useContext(AuthContext);
  if (!user) throw new Error("useMe() used outside the signed-in app");
  return user;
}

export function isAdmin(user: User): boolean {
  return user.role === "admin" || user.role === "superadmin";
}
