import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { iconOptions, iconSuggestions } from "@/features/configuration/emby-server-icon-catalog";
import { EmbyServerIcon } from "@/features/emby-live/components/emby-server-icon";

describe("EmbyServerIcon", () => {
  it("renders a Font Awesome server glyph for the configured regular legacy style", () => {
    const markup = renderToStaticMarkup(
      <EmbyServerIcon icon="fa-server" iconStyle="regular" />,
    );

    expect(markup).toContain('data-prefix="fas"');
    expect(markup).toContain('data-icon="server"');
  });

  it("renders a Font Awesome server glyph for the solid server icon style", () => {
    const markup = renderToStaticMarkup(
      <EmbyServerIcon icon="fa-server" iconStyle="solid" />,
    );

    expect(markup).toContain('data-prefix="fas"');
    expect(markup).toContain('data-icon="server"');
  });

  it("keeps every suggested legacy Font Awesome value renderable in React", () => {
    expect(iconSuggestions).toEqual(iconOptions.map((option) => option.value));
    expect(iconOptions.some((option) => option.value === "fa-satellite-dish")).toBe(true);
    expect(iconOptions.some((option) => option.value === "fa-graduation-cap")).toBe(true);
  });
});
