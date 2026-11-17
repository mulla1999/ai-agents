import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Role, User } from "../api/types";
import { Layout } from "../components/Layout";
import { renderWithProviders } from "./utils";

const person = (role: Role): User => ({
  id: 1,
  email: `${role}@example.com`,
  full_name: null,
  role,
  status: "active",
  email_verified: true,
  created_at: null,
  last_login_at: null,
});

const renderAs = (role: Role) => renderWithProviders(<Layout user={person(role)}>content</Layout>);

describe("Layout navigation", () => {
  it("hides administration from regular users", () => {
    renderAs("user");
    expect(screen.queryByText("Administration")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /platform settings/i })).not.toBeInTheDocument();
  });

  it("shows administration to admins, without platform settings", () => {
    renderAs("admin");
    expect(screen.getByText("Administration")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /platform settings/i })).not.toBeInTheDocument();
  });

  it("shows platform settings only to the superadmin", () => {
    renderAs("superadmin");
    expect(screen.getByText("Administration")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /platform settings/i })).toBeInTheDocument();
  });
});
