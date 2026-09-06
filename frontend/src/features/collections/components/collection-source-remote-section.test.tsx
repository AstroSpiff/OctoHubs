import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  CollectionSourceRemoteSection,
} from "@/features/collections/components/collection-source-remote-section";
import { safeCollectionProviderLink } from "@/features/collections/collection-provider-links";

describe("CollectionSourceRemoteSection", () => {
  it("does not claim an empty provider list before its first snapshot", () => {
    const unresolved = renderToStaticMarkup(
      <CollectionSourceRemoteSection
        title="Liste Trakt"
        defaultSourceType="trakt_list"
        unavailable={false}
        loading
        hasData={false}
        busy={false}
        items={[]}
        onRefresh={() => undefined}
        onChoose={() => undefined}
      />,
    );
    const resolvedEmpty = renderToStaticMarkup(
      <CollectionSourceRemoteSection
        title="Liste Trakt"
        defaultSourceType="trakt_list"
        unavailable={false}
        loading={false}
        hasData
        busy={false}
        items={[]}
        onRefresh={() => undefined}
        onChoose={() => undefined}
      />,
    );

    expect(unresolved).toContain("Caricamento liste trakt");
    expect(unresolved).not.toContain("Nessuna lista disponibile");
    expect(resolvedEmpty).toContain("Nessuna lista disponibile");
  });

  it("keeps a stale empty snapshot visible beside a refresh error", () => {
    const markup = renderToStaticMarkup(
      <CollectionSourceRemoteSection
        title="Liste MDBList"
        defaultSourceType="mdblist"
        unavailable={false}
        loading={false}
        hasData
        busy={false}
        error="Refresh non riuscito"
        items={[]}
        onRefresh={() => undefined}
        onChoose={() => undefined}
      />,
    );

    expect(markup).toContain("Refresh non riuscito");
    expect(markup).toContain("Nessuna lista disponibile");
  });

  it("locks refresh and selection while another source mutation is running", () => {
    const markup = renderToStaticMarkup(
      <CollectionSourceRemoteSection
        title="Liste Trakt"
        defaultSourceType="trakt_list"
        unavailable={false}
        loading={false}
        hasData
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
