import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { LibraryGroupCard } from "@/features/libraries/components/library-group-card";

const group = {
  group_name: "Cinema",
  collection_type: "movies",
  servers: ["green"],
  libraries: [
    {
      server_id: "green",
      library_id: "films",
      library_name: "Film",
      server_icon: "fa-film",
      server_icon_style: "regular",
      server_icon_color: "#8B5CF6",
    },
  ],
};

describe("LibraryGroupCard", () => {
  it("keeps the compact legacy disclosure in the group header", () => {
    const markup = renderToStaticMarkup(
      <LibraryGroupCard
        group={group}
        workflowMode={false}
        scanning={false}
        scanJobs={[]}
        scanHistory={[]}
        libraryScanBusy={false}
        onScan={() => undefined}
        onScanLibrary={() => undefined}
      />,
    );

    expect(markup).toContain('class="library-group-disclosure"');
    expect(markup).toContain('aria-expanded="false"');
    expect(markup).not.toContain("<summary");
  });

  it("keeps the server identity ahead of the library name in the expanded rows", () => {
    const markup = renderToStaticMarkup(
      <LibraryGroupCard
        group={group}
        workflowMode={false}
        scanning
        scanJobs={[]}
        scanHistory={[]}
        libraryScanBusy={false}
        onScan={() => undefined}
        onScanLibrary={() => undefined}
      />,
    );

    expect(markup).toContain('data-prefix="fas"');
    expect(markup.indexOf("green")).toBeLessThan(markup.indexOf("Film"));
  });

  it("prevents duplicate group and library scans while their tracked job is active", () => {
    const markup = renderToStaticMarkup(
      <LibraryGroupCard
        group={group}
        workflowMode={false}
        scanning={false}
        scanJobs={[
          {
            job_id: "job-1",
            server_id: "green",
            library_ids: ["films"],
            group_name: "Cinema",
            status: "active",
            progress: 0.5,
          },
        ]}
        scanHistory={[]}
        libraryScanBusy={false}
        onScan={() => undefined}
        onScanLibrary={() => undefined}
      />,
    );

    expect(markup.match(/<button[^>]*\sdisabled(?:=|\s|>)/g)).toHaveLength(4);
  });

  it("shows the latest tracked activity for the matching group only", () => {
    const markup = renderToStaticMarkup(
      <LibraryGroupCard
        group={group}
        workflowMode={false}
        scanning={false}
        scanJobs={[]}
        scanHistory={[
          {
            id: "old",
            group_name: "Cinema",
            scan_type: "content",
            status: "completed",
            completed_at: "2026-08-20T10:00:00Z",
          },
          {
            id: "latest",
            group_name: "Cinema",
            scan_type: "metadata",
            status: "completed",
            completed_at: "2026-08-21T10:00:00Z",
          },
          {
            id: "other",
            group_name: "Serie",
            status: "error",
            completed_at: "2026-08-22T10:00:00Z",
          },
        ]}
        libraryScanBusy={false}
        onScan={() => undefined}
        onScanLibrary={() => undefined}
      />,
    );

    expect(markup).toContain("Ultima attività registrata");
    expect(markup).toContain("Metadata");
    expect(markup).not.toContain("Errore");
  });
});
