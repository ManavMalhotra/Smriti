import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { afterEach, describe, expect, it, vi } from "vitest";
import Auth from "../pages/Auth";

function jsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Auth", () => {
  it("starts on sign in and can switch to registration", async () => {
    const user = userEvent.setup();
    render(<Auth onAuthenticated={() => {}} />);

    expect(screen.getByRole("heading", { name: "Sign in" })).toHaveFocus();
    expect(screen.queryByLabelText("Patient alias")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Create an account" }));

    expect(screen.getByRole("heading", { name: "Create your account" })).toHaveFocus();
    expect(screen.getByLabelText("Patient alias")).toBeInTheDocument();
    expect(screen.getByLabelText("Username")).toHaveAttribute("autocomplete", "username");
    expect(screen.getByLabelText("Password")).toHaveAttribute("autocomplete", "new-password");
  });

  it("registers an account and passes the patient to the app", async () => {
    const patient = { id: "pat-1", alias: "P-02", username: "patient-one" };
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(patient, 201));
    vi.stubGlobal("fetch", fetchMock);
    const onAuthenticated = vi.fn();
    const user = userEvent.setup();
    render(<Auth onAuthenticated={onAuthenticated} />);

    await user.click(screen.getByRole("button", { name: "Create an account" }));
    await user.type(screen.getByLabelText("Patient alias"), "P-02");
    await user.selectOptions(screen.getByLabelText("Sex"), "F");
    await user.type(screen.getByLabelText("Username"), "patient-one");
    await user.type(screen.getByLabelText("Password"), "test-password-123");
    await user.click(screen.getByRole("button", { name: "Create account" }));

    expect(onAuthenticated).toHaveBeenCalledWith(patient);
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/auth/register");
    expect(JSON.parse(options.body)).toEqual({
      alias: "P-02",
      username: "patient-one",
      password: "test-password-123",
      sex: "F",
    });
  });

  it("shows the server error without losing the form", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      jsonResponse(
        {
          error: {
            code: "invalid_credentials",
            message: "Invalid username or password.",
            field: null,
          },
        },
        401,
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<Auth onAuthenticated={() => {}} />);

    await user.type(screen.getByLabelText("Username"), "patient-one");
    await user.type(screen.getByLabelText("Password"), "wrong-password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Invalid username or password.",
    );
    expect(screen.getByLabelText("Username")).toHaveValue("patient-one");
    expect(screen.getByLabelText("Password")).toHaveValue("wrong-password");
  });

  it("has no automatically detectable accessibility violations", async () => {
    const { container } = render(<Auth onAuthenticated={() => {}} />);

    expect(await axe(container)).toHaveNoViolations();
  });
});
