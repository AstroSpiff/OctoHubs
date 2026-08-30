import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ServerIdentity } from "@/features/users/components/server-identity";

describe("ServerIdentity", () => {
  it("keeps a readable server name alongside its configured identity", () => {
    const markup = renderToStaticMarkup(
      <ServerIdentity
        name="Green"
        icon="server"
        color="#4f7ea8"
        iconStyle="regular"
      />,
    );

    expect(markup).toContain("Green");
    expect(markup).toContain("users-server-identity");
    expect(markup).toContain("#4f7ea8");
  });
});
