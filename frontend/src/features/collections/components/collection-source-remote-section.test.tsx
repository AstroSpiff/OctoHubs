import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  CollectionSourceRemoteSection,
} from "@/features/collections/components/collection-source-remote-section";
import { safeCollectionProviderLink } from "@/features/collections/collection-provider-links";

describe("CollectionSourceRemoteSection", () => {
  it("locks refresh and selection while another source mutation is running", () => {
    const markup = renderToStaticMarkup(
      <CollectionSourceRemoteSection
        title="Liste Trakt"
        defaultSourceType="trakt_list"
        unavailable={false}
        loading={false}
        busy
        items={[{ name: "Preferiti", source_value: "roy/preferiti" }]}
        onRefresh={() => undefined}
        onChoose={() => undefined}
      />,
    );

    expect(markup.match(/<button[^>]*\sdisabled(?:=|\s|>)/g)).toHaveLength(2);
  });

  it("accepts only canonical HTTPS provider hosts and strips queries", () => {
    expect(
      safeCollectionProviderLink(
        "https://mdblist.com/lists/roy/external/2868?token=CANARY#fragment",
        "mdblist",
      ),
    ).toBe("https://mdblist.com/lists/roy/external/2868");
    expect(
      safeCollectionProviderLink(
        "https://mdblist.example/lists/roy?token=CANARY",
        "mdblist",
      ),
    ).toBe("");
  });
});
