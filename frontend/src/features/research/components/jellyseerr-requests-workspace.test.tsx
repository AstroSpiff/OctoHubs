import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { JellyseerrRequestsWorkspace } from "@/features/research/components/jellyseerr-requests-workspace";
import type { ResearchOverview } from "@/features/research/types";

const unconfiguredOverview = {
  success: true,
  has_config: false,
  qbittorrent_available: false,
  scan: {},
  results: {},
  requests: [],
  movie_requests: [],
  tv_requests: [],
  all_requests: [],
  all_movie_requests: [],
  all_tv_requests: [],
  search_rules: {} as ResearchOverview["search_rules"],
  search_defaults: { target_languages: [], exclude_tags: [] },
  movie_sort_options: [],
  tv_sort_options: [],
  auto_tasks: {},
  probe_counts: { blacklist: 0, incomplete: 0 },
} satisfies ResearchOverview;

describe("JellyseerrRequestsWorkspace", () => {
  it("keeps the TV tab reachable when there are no movie requests", () => {
    const client = new QueryClient();
    const tvOnly = {
      ...unconfiguredOverview,
      has_config: true,
      requests: [{ id: 7, media_type: "tv", title: "Serie" }],
      tv_requests: [{ id: 7, media_type: "tv", title: "Serie" }],
      all_requests: [{ id: 7, media_type: "tv", title: "Serie" }],
      all_tv_requests: [{ id: 7, media_type: "tv", title: "Serie" }],
    } as ResearchOverview;
    const markup = renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <JellyseerrRequestsWorkspace overview={tvOnly} onRefresh={() => undefined} />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(markup).toContain("Serie TV");
    expect(markup).not.toContain("Nessuna richiesta Jellyseerr da monitorare.");
  });

  it("explains missing configuration instead of presenting an empty request list", () => {
    const client = new QueryClient();
    const markup = renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <JellyseerrRequestsWorkspace
            overview={unconfiguredOverview}
            onRefresh={() => undefined}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(markup).toContain("Configura Jellyseerr e gli altri servizi necessari");
    expect(markup).toContain('href="/configuration?focus=configuration-connections#services"');
    expect(markup).not.toContain("Nessuna richiesta Jellyseerr da monitorare.");
  });
});
