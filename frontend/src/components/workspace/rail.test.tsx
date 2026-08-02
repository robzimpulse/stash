import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const replace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace }),
  usePathname: () => "/p/123",
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/workspace-store", () => ({
  useWorkspace: (selector: (s: unknown) => unknown) =>
    selector({ setRailSection: vi.fn() }),
}));

import Rail from "./rail";

describe("Rail navigation", () => {
  beforeEach(() => {
    replace.mockClear();
  });

  it("navigates to /skills when Skills is tapped", () => {
    render(<Rail user={{ display_name: "A", name: "a", email: "" } as never} onLogout={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Skills" }));
    expect(replace).toHaveBeenCalledWith("/skills");
  });

  it("navigates to /sessions when Sessions is tapped", () => {
    render(<Rail user={{ display_name: "A", name: "a", email: "" } as never} onLogout={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Sessions" }));
    expect(replace).toHaveBeenCalledWith("/sessions");
  });

  it("navigates to /tools when Tools is tapped", () => {
    render(<Rail user={{ display_name: "A", name: "a", email: "" } as never} onLogout={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Tools" }));
    expect(replace).toHaveBeenCalledWith("/tools");
  });

  it("keeps Files on the current path via ?section= (no regression)", () => {
    render(<Rail user={{ display_name: "A", name: "a", email: "" } as never} onLogout={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Files" }));
    expect(replace).toHaveBeenCalledWith("/p/123?section=files");
  });
});
