import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ProbeServerTabs } from "@/features/probe/components/probe-server-tabs";

describe("ProbeServerTabs", () => {
  it("renders the configured icon presentation for each Emby server", () => {
    const markup = renderToStaticMarkup(
      <ProbeServerTabs
        servers={[
          {
            id: "purple",
            name: "Purple",
            icon: "fa-film",
            icon_style: "regular",
            icon_color: "#8B5CF6",
          },
        ]}
        value="purple"
        onChange={() => true}
      />,
    );

    expect(markup).toContain('data-prefix="fas"');
    expect(markup).toContain("color:#8B5CF6");
  });
});
