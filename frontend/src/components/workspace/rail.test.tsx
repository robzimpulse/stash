import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { replace, useWorkspace } = vi.hoisted(() => {
  const replace = vi.fn();
  const useWorkspace = vi.fn((selector: (s: unknown) => unknown) =>
    selector({ setRailSection: vi.fn() }),
  );
  // The Files button resumes the explorer's last location when the user is
  // elsewhere in the app; point it somewhere distinct so the resume target is
  // observable.
  (useWorkspace as unknown as { getState: () => unknown }).getState = () => ({
    lastVfsUrl: "/f/abc",
  });
  return { replace, useWorkspace };
});

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace }),
  usePathname: () => "/sessions",
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/workspace-store", () => ({ useWorkspace }));

import Rail from "./rail";

// Tools is gated to the orgs that still use it (lib/flags.ts); a heaviai.com
// email turns the Tools button on.
const user = { display_name: "A", name: "a", email: "a@heaviai.com" } as never;

describe("Rail navigation", () => {
  beforeEach(() => {
    replace.mockClear();
  });

  it("navigates to /skills when Skills is tapped", () => {
    render(<Rail user={user} onLogout={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Skills" }));
    expect(replace).toHaveBeenCalledWith("/skills");
  });

  it("navigates to /sessions when Sessions is tapped", () => {
    render(<Rail user={user} onLogout={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Sessions" }));
    expect(replace).toHaveBeenCalledWith("/sessions");
  });

  it("navigates to /tools when Tools is tapped", () => {
    render(<Rail user={user} onLogout={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Tools" }));
    expect(replace).toHaveBeenCalledWith("/tools");
  });

  it("resumes the explorer's last location when Files is tapped", () => {
    render(<Rail user={user} onLogout={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Files" }));
    expect(replace).toHaveBeenCalledWith("/f/abc");
  });
});
