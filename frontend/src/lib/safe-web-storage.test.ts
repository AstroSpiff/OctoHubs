// @vitest-environment jsdom

import { afterEach, describe, expect, it } from "vitest";

import {
  browserLocalStorage,
  readStoredValue,
  writeStoredValue,
} from "@/lib/safe-web-storage";

const localStorageDescriptor = Object.getOwnPropertyDescriptor(window, "localStorage");

afterEach(() => {
  if (localStorageDescriptor) {
    Object.defineProperty(window, "localStorage", localStorageDescriptor);
  }
});

describe("safe web storage", () => {
  it("falls back when the browser denies access to localStorage", () => {
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      get: () => {
        throw new DOMException("denied", "SecurityError");
      },
    });

    expect(browserLocalStorage()).toBeNull();
  });

  it("contains failures from storage reads and writes", () => {
    const storage = {
      getItem: () => {
        throw new DOMException("denied", "SecurityError");
      },
      setItem: () => {
        throw new DOMException("quota", "QuotaExceededError");
      },
    };

    expect(readStoredValue(storage, "preference")).toBeNull();
    expect(writeStoredValue(storage, "preference", "value")).toBe(false);
  });
});
