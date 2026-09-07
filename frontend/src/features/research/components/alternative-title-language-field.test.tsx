// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AlternativeTitleLanguageField } from "@/features/research/components/alternative-title-language-field";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

describe("AlternativeTitleLanguageField", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("uses independent labels for the checkbox and language select", async () => {
    const onCheckedChange = vi.fn();
    await act(async () => {
      root.render(
        <AlternativeTitleLanguageField
          checked
          label="Titoli alternativi in lingua"
          language="it"
          onCheckedChange={onCheckedChange}
          onLanguageChange={() => undefined}
        />,
      );
    });

    const checkbox = container.querySelector<HTMLInputElement>('input[type="checkbox"]');
    const select = container.querySelector("select");
    const labels = [...container.querySelectorAll("label")];
    expect(labels).toHaveLength(2);
    expect(labels[0]?.control).toBe(checkbox);
    expect(labels[1]?.control).toBe(select);

    act(() => labels[0]?.querySelector("span")?.click());
    expect(onCheckedChange).toHaveBeenCalledWith(false);
  });
});
