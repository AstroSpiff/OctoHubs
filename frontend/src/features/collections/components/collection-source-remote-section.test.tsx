import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { CollectionSourceRemoteSection } from "@/features/collections/components/collection-source-remote-section";

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
});
