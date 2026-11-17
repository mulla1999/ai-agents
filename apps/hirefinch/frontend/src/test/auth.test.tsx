import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { LoginPage, RegisterPage } from "../pages/AuthPages";
import { mockFetch, renderWithProviders } from "./utils";

describe("LoginPage", () => {
  it("asks for the second factor and posts it to /auth/login/2fa", async () => {
    const calls = mockFetch(({ method, path }) => {
      if (path === "/auth/google/config") return { json: { enabled: false } };
      if (method === "POST" && path === "/auth/login") return { json: { authenticated: false, two_factor_required: true, challenge: "ch-1" } };
      if (method === "POST" && path === "/auth/login/2fa") return { json: { authenticated: true } };
    });
    const onSignedIn = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<LoginPage onSignedIn={onSignedIn} />, { route: "/login" });

    await user.type(screen.getByLabelText("Email"), "a@example.com");
    await user.type(screen.getByLabelText("Password"), "correct horse battery");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    const code = await screen.findByLabelText("Authentication code");
    expect(onSignedIn).not.toHaveBeenCalled();
    await user.type(code, " 123456 ");
    await user.click(screen.getByRole("button", { name: /verify and sign in/i }));

    await waitFor(() => expect(onSignedIn).toHaveBeenCalledTimes(1));
    const second = calls.find((c) => c.path === "/auth/login/2fa");
    expect(second?.method).toBe("POST");
    expect(second?.body).toEqual({ challenge: "ch-1", code: "123456" });
  });

  it("goes straight to the code step when the URL carries #challenge, then clears the hash", async () => {
    mockFetch(({ path }) => (path === "/auth/google/config" ? { json: { enabled: false } } : undefined));
    window.history.replaceState(null, "", "/login#challenge=from-google");
    renderWithProviders(<LoginPage onSignedIn={() => undefined} />, { route: "/login" });

    expect(await screen.findByLabelText("Authentication code")).toBeInTheDocument();
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
    expect(window.location.hash).toBe("");
  });
});

describe("RegisterPage", () => {
  it("shows the development link when the API returns one", async () => {
    mockFetch(({ method, path }) => {
      if (path === "/auth/google/config") return { json: { enabled: false } };
      if (method === "POST" && path === "/auth/register") {
        return { json: { message: "Check your inbox.", dev_link: "http://localhost/verify#token=abc" } };
      }
    });
    const user = userEvent.setup();
    renderWithProviders(<RegisterPage />, { route: "/register" });

    await user.type(screen.getByLabelText("Email"), "new@example.com");
    await user.type(screen.getByLabelText("Password"), "a long enough password");
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: /create account/i }));

    expect(await screen.findByText(/no platform email is configured/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "http://localhost/verify#token=abc" })).toHaveAttribute("href", "http://localhost/verify#token=abc");
  });
});
