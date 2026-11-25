import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { App } from "./App";

afterEach(() => {
  cleanup();
});

describe("App (BS-001 smoke)", () => {
  it("renders the BookScope shell heading", () => {
    render(<App />);
    expect(screen.getByRole("heading", { level: 1, name: "BookScope" })).toBeInTheDocument();
  });

  it("states that the reader is not implemented rather than implying features", () => {
    render(<App />);
    expect(screen.getByText("Reader not yet implemented.")).toBeInTheDocument();
  });
});
