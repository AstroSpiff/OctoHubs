import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

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
});
