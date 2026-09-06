// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LatestNotificationPreview } from "@/features/emby-latest/components/latest-notification-preview";
import type {
  LatestItem,
  LatestPreviewRequest,
} from "@/features/emby-latest/types";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

const movie = {
  server_id: "green",
  item_id: "movie-1",
  title: "Film A",
} as LatestItem;
const newerMovie = {
  server_id: "green",
  item_id: "movie-2",
  title: "Film B",
} as LatestItem;

describe("LatestNotificationPreview", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    vi.useFakeTimers();
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.useRealTimers();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it("hides a completed preview as soon as its selected item is cleared", () => {
    const request: LatestPreviewRequest = {
      template: "{{ title }}",
      items: { movie },
    };
    act(() => {
      root.render(
        <LatestNotificationPreview
          template={request.template}
          movies={[movie]}
          series={[]}
          result={{
            success: true,
            previews: {
              movie: { message: "Anteprima Film A", image_enabled: false },
            },
          }}
          request={request}
          loading={false}
          onPreview={vi.fn()}
        />,
      );
    });
    expect(container.textContent).toContain("Anteprima Film A");

    const select = container.querySelector<HTMLSelectElement>("select");
    act(() => {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLSelectElement.prototype,
        "value",
      )?.set;
      setter?.call(select, "");
      select?.dispatchEvent(new Event("change", { bubbles: true }));
    });

    expect(container.textContent).toContain("Nessun contenuto");
    expect(container.textContent).not.toContain("Anteprima Film A");
  });

  it("does not show an out-of-order result for a previous item or template", () => {
    const onPreview = vi.fn();
    const oldRequest: LatestPreviewRequest = {
      template: "{{ title }}",
      items: { movie },
    };
    const oldResult = {
      success: true,
      previews: {
        movie: { message: "Anteprima Film A", image_enabled: false },
      },
    };
    act(() => {
      root.render(
        <LatestNotificationPreview
          template={oldRequest.template}
          movies={[movie, newerMovie]}
          series={[]}
          result={oldResult}
          request={oldRequest}
          loading={false}
          onPreview={onPreview}
        />,
      );
    });
    expect(container.textContent).toContain("Anteprima Film A");

    const select = container.querySelector<HTMLSelectElement>("select");
    act(() => {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLSelectElement.prototype,
        "value",
      )?.set;
      setter?.call(select, "green-movie-2");
      select?.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(container.textContent).toContain("Film B");
    expect(container.textContent).not.toContain("Anteprima Film A");

    act(() => {
      root.render(
        <LatestNotificationPreview
          template="Nuovo {{ title }}"
          movies={[movie, newerMovie]}
          series={[]}
          result={oldResult}
          request={oldRequest}
          loading={false}
          onPreview={onPreview}
        />,
      );
    });
    expect(container.textContent).not.toContain("Anteprima Film A");

    const currentRequest: LatestPreviewRequest = {
      template: "Nuovo {{ title }}",
      items: { movie: newerMovie },
    };
    act(() => {
      root.render(
        <LatestNotificationPreview
          template={currentRequest.template}
          movies={[movie, newerMovie]}
          series={[]}
          result={{
            success: true,
            previews: {
              movie: { message: "Anteprima Film B", image_enabled: false },
            },
          }}
          request={currentRequest}
          loading={false}
          onPreview={onPreview}
        />,
      );
    });
    expect(container.textContent).toContain("Anteprima Film B");
  });

  it("hides a stale completion when metadata changes for the same item", () => {
    const oldMovie = {
      ...movie,
      overview: "Prima sinossi",
      changes: [{ quality: "1080p", video_codec: "H264" }],
      image_url: "/api/emby/green/items/movie-1/images/primary",
    };
    const updatedMovie = {
      ...oldMovie,
      overview: "Sinossi aggiornata",
      changes: [{ quality: "2160p", video_codec: "HEVC" }],
      image_url: "/api/emby/green/items/movie-1/images/primary?tag=new",
    };
    const staleRequest: LatestPreviewRequest = {
      template: "{{ overview }} · {{ quality }}",
      items: { movie: oldMovie },
    };
    const staleResult = {
      success: true,
      previews: {
        movie: { message: "Prima sinossi · 1080p", image_enabled: true },
      },
    };

    act(() => {
      root.render(
        <LatestNotificationPreview
          template={staleRequest.template}
          movies={[oldMovie]}
          series={[]}
          result={staleResult}
          request={staleRequest}
          loading={false}
          onPreview={vi.fn()}
        />,
      );
    });
    expect(container.textContent).toContain("Prima sinossi · 1080p");

    act(() => {
      root.render(
        <LatestNotificationPreview
          template={staleRequest.template}
          movies={[updatedMovie]}
          series={[]}
          result={staleResult}
          request={staleRequest}
          loading={true}
          onPreview={vi.fn()}
        />,
      );
    });

    expect(container.textContent).toContain("Film A");
    expect(container.textContent).not.toContain("Prima sinossi · 1080p");
  });
});
