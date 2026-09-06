// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { useLatestActionFeedback } from "@/features/emby-latest/use-latest-action-feedback";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason: unknown) => void;
};

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((complete, fail) => {
    resolve = complete;
    reject = fail;
  });
  return { promise, reject, resolve };
}

let latestFeedback: ReturnType<typeof useLatestActionFeedback> | undefined;

function Harness() {
  latestFeedback = useLatestActionFeedback();
  return null;
}

describe("useLatestActionFeedback", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    latestFeedback = undefined;
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    act(() => root.render(<Harness />));
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("ignores an older completion after a newer action has started", async () => {
    const older = deferred<{ message: string }>();
    const newer = deferred<{ message: string }>();
    let olderRun!: Promise<{ message: string }>;
    let newerRun!: Promise<{ message: string }>;

    act(() => {
      olderRun = latestFeedback!.run(() => older.promise, "Older fallback");
      newerRun = latestFeedback!.run(() => newer.promise, "Newer fallback");
    });
    await act(async () => {
      older.resolve({ message: "Older completed" });
      await olderRun;
    });
    expect(latestFeedback?.feedback).toBeNull();

    await act(async () => {
      newer.resolve({ message: "Newer completed" });
      await newerRun;
    });
    expect(latestFeedback?.feedback).toEqual({
      message: "Newer completed",
      scope: "page",
      tone: "success",
    });
  });

  it("does not replace newer success feedback with an older late error", async () => {
    const older = deferred<{ message: string }>();
    const newer = deferred<{ message: string }>();
    let olderRun!: Promise<{ message: string }>;
    let newerRun!: Promise<{ message: string }>;

    act(() => {
      olderRun = latestFeedback!.run(() => older.promise, "Older fallback");
      newerRun = latestFeedback!.run(() => newer.promise, "Newer fallback");
    });
    await act(async () => {
      newer.resolve({ message: "Newer completed" });
      await newerRun;
    });
    await act(async () => {
      older.reject(new Error("Older failed"));
      await olderRun.catch(() => undefined);
    });

    expect(latestFeedback?.feedback).toEqual({
      message: "Newer completed",
      scope: "page",
      tone: "success",
    });
  });

  it("clears an older preset delete error when a newer preset save succeeds", async () => {
    await act(async () => {
      await latestFeedback
        ?.run(
          () => Promise.reject(new Error("Delete preset failed")),
          "Preset deleted",
          "preset",
        )
        .catch(() => undefined);
    });
    expect(latestFeedback?.errorFor("preset")).toBe("Delete preset failed");

    await act(async () => {
      await latestFeedback?.run(
        () => Promise.resolve({ message: "Preset saved" }),
        "Preset saved",
        "preset",
      );
    });

    expect(latestFeedback?.errorFor("preset")).toBeUndefined();
    expect(latestFeedback?.notice).toEqual({
      message: "Preset saved",
      scope: "preset",
      tone: "success",
    });
  });

  it("clears an older rule delete error when a newer rule save succeeds", async () => {
    await act(async () => {
      await latestFeedback
        ?.run(
          () => Promise.reject(new Error("Delete rule failed")),
          "Rule deleted",
          "rule",
        )
        .catch(() => undefined);
    });
    expect(latestFeedback?.errorFor("rule")).toBe("Delete rule failed");

    await act(async () => {
      await latestFeedback?.run(
        () => Promise.resolve({ message: "Rule saved" }),
        "Rule saved",
        "rule",
      );
    });

    expect(latestFeedback?.errorFor("rule")).toBeUndefined();
    expect(latestFeedback?.notice).toEqual({
      message: "Rule saved",
      scope: "rule",
      tone: "success",
    });
  });

  it("presents a partial notification outcome as a warning", async () => {
    await act(async () => {
      await latestFeedback?.run(
        () => Promise.resolve({
          success: false,
          status: "partial",
          message: "Notifiche inviate: 1. Errori: 1.",
          sent: 1,
          failed: 1,
        }),
        "Notifications sent",
      );
    });

    expect(latestFeedback?.notice).toEqual({
      message: "Notifiche inviate: 1. Errori: 1.",
      scope: "page",
      tone: "warning",
    });
  });

  it("keeps failures from independent scopes when completions are inverted", async () => {
    const preset = deferred<{ message: string }>();
    const page = deferred<{ message: string }>();
    let presetRun!: Promise<{ message: string }>;
    let pageRun!: Promise<{ message: string }>;

    act(() => {
      presetRun = latestFeedback!.run(
        () => preset.promise,
        "Preset saved",
        "preset",
      );
      pageRun = latestFeedback!.run(() => page.promise, "Page refreshed", "page");
    });
    await act(async () => {
      page.resolve({ message: "Page refreshed" });
      await pageRun;
    });
    await act(async () => {
      preset.reject(new Error("Preset failed"));
      await presetRun.catch(() => undefined);
    });

    expect(latestFeedback?.errorFor("preset")).toBe("Preset failed");
    expect(latestFeedback?.notice).toEqual({
      message: "Page refreshed",
      scope: "page",
      tone: "success",
    });
  });
});
