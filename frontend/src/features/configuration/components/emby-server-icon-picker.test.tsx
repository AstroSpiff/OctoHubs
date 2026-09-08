// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { EmbyServerIconPicker } from "@/features/configuration/components/emby-server-icon-picker";

describe("EmbyServerIconPicker", () => {
  it("shows the Font Awesome icon and color controls without exposing a non-universal outline style", () => {
    const markup = renderToStaticMarkup(
      <EmbyServerIconPicker
        icon="fa-server"
        color="#3b82f6"
        disabled={false}
        onIconChange={() => undefined}
        onColorChange={() => undefined}
      />,
    );

    expect(markup).toContain('data-prefix="fas"');
    expect(markup).not.toContain('aria-label="Stile icona"');
  });

  it("exposes the quick-color selection and peer transitions", () => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    const container = document.createElement("div");
    const root = createRoot(container);
    const onColorChange = vi.fn();

    const renderPicker = (color: string) => act(() => root.render(
      <EmbyServerIconPicker
        icon="fa-server"
        color={color}
        disabled={false}
        onIconChange={() => undefined}
        onColorChange={onColorChange}
      />,
    ));

    renderPicker("#3b82f6");
    const blue = container.querySelector<HTMLButtonElement>('[aria-label="Usa colore #3B82F6"]');
    const green = container.querySelector<HTMLButtonElement>('[aria-label="Usa colore #22C55E"]');
    expect(blue?.getAttribute("aria-pressed")).toBe("true");
    expect(green?.getAttribute("aria-pressed")).toBe("false");

    act(() => green?.click());
    expect(onColorChange).toHaveBeenCalledWith("#22C55E");
    renderPicker("#22c55e");
    expect(blue?.getAttribute("aria-pressed")).toBe("false");
    expect(green?.getAttribute("aria-pressed")).toBe("true");

    act(() => root.unmount());
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });
});
