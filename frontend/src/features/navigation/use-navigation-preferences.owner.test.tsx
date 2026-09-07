// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/features/navigation/navigation-preferences-api", () => ({
  saveNavigationPreferences: vi.fn(),
}));

import { saveNavigationPreferences } from "@/features/navigation/navigation-preferences-api";
import type { NavigationPreferences } from "@/features/navigation/navigation-preferences";
import { useNavigationPreferences } from "@/features/navigation/use-navigation-preferences";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

function Harness({ accountId, preferences }: { accountId: number; preferences: NavigationPreferences }) {
  const navigation = useNavigationPreferences(preferences, accountId);
  return (
    <button
      data-primary={navigation.preferences.primary_navigation}
      data-secondary={navigation.preferences.secondary_navigation}
      data-pending={String(navigation.isSaving)}
      data-error={navigation.error?.message || ""}
      onClick={() => navigation.updatePreferences({ primary_navigation: "sidebar" })}
      type="button"
    >
      update
    </button>
  );
}

describe("navigation preferences owner boundary", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  let client: QueryClient;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  });

  afterEach(() => {
    act(() => root.unmount());
    client.clear();
    container.remove();
    vi.clearAllMocks();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("ignores a previous owner's late mutation callback", async () => {
    let resolveSave: ((value: NavigationPreferences) => void) | undefined;
    vi.mocked(saveNavigationPreferences).mockReturnValue(new Promise((resolve) => {
      resolveSave = resolve;
    }));
    const ownerA = { primary_navigation: "top", secondary_navigation: "tabs" } as const;
    const ownerB = { primary_navigation: "top", secondary_navigation: "sidebar" } as const;
    client.setQueryData(["session"], { user: { id: 1 }, preferences: ownerA });

    await act(async () => {
      root.render(<QueryClientProvider client={client}><Harness accountId={1} preferences={ownerA} /></QueryClientProvider>);
    });
    act(() => container.querySelector("button")?.click());

    client.setQueryData(["session"], { user: { id: 2 }, preferences: ownerB });
    await act(async () => {
      root.render(<QueryClientProvider client={client}><Harness accountId={2} preferences={ownerB} /></QueryClientProvider>);
    });
    resolveSave?.({ primary_navigation: "sidebar", secondary_navigation: "tabs" });
    await act(async () => Promise.resolve());

    expect(container.querySelector("button")?.dataset).toMatchObject({
      primary: "top",
      secondary: "sidebar",
    });
    expect(client.getQueryData<{ user: { id: number }; preferences: NavigationPreferences }>(["session"])).toEqual({
      user: { id: 2 },
      preferences: ownerB,
    });
  });

  it("resets pending and error state when the account owner changes", async () => {
    let rejectSave: ((reason: Error) => void) | undefined;
    vi.mocked(saveNavigationPreferences).mockReturnValue(new Promise((_resolve, reject) => {
      rejectSave = reject;
    }));
    const ownerA = { primary_navigation: "top", secondary_navigation: "tabs" } as const;
    const ownerB = { primary_navigation: "sidebar", secondary_navigation: "sidebar" } as const;

    await act(async () => {
      root.render(<QueryClientProvider client={client}><Harness accountId={1} preferences={ownerA} /></QueryClientProvider>);
    });
    act(() => container.querySelector("button")?.click());
    expect(container.querySelector("button")?.dataset.pending).toBe("true");

    await act(async () => {
      root.render(<QueryClientProvider client={client}><Harness accountId={2} preferences={ownerB} /></QueryClientProvider>);
    });
    expect(container.querySelector("button")?.dataset).toMatchObject({
      error: "",
      pending: "false",
      primary: "sidebar",
      secondary: "sidebar",
    });

    await act(async () => {
      rejectSave?.(new Error("errore owner A"));
      await Promise.resolve();
    });

    expect(container.querySelector("button")?.dataset.error).toBe("");
    expect(container.querySelector("button")?.dataset.pending).toBe("false");
  });

  it("rejects owner A results that arrive after an A to B to A cycle", async () => {
    let resolveSave: ((value: NavigationPreferences) => void) | undefined;
    vi.mocked(saveNavigationPreferences).mockReturnValue(new Promise((resolve) => {
      resolveSave = resolve;
    }));
    const ownerA = { primary_navigation: "top", secondary_navigation: "tabs" } as const;
    const ownerB = { primary_navigation: "sidebar", secondary_navigation: "sidebar" } as const;

    await act(async () => {
      root.render(<QueryClientProvider client={client}><Harness accountId={1} preferences={ownerA} /></QueryClientProvider>);
    });
    act(() => container.querySelector("button")?.click());
    await act(async () => {
      root.render(<QueryClientProvider client={client}><Harness accountId={2} preferences={ownerB} /></QueryClientProvider>);
    });
    await act(async () => {
      root.render(<QueryClientProvider client={client}><Harness accountId={1} preferences={ownerA} /></QueryClientProvider>);
    });
    await act(async () => {
      resolveSave?.({ primary_navigation: "sidebar", secondary_navigation: "tabs" });
      await Promise.resolve();
    });

    expect(container.querySelector("button")?.dataset).toMatchObject({
      error: "",
      pending: "false",
      primary: "top",
      secondary: "tabs",
    });
  });
});
