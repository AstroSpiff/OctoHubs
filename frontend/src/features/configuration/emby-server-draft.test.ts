import { describe, expect, it } from "vitest";

import {
  embyServerInputFromSettings,
  refreshedEmbyServerDraft,
} from "@/features/configuration/emby-server-draft";

const saved = embyServerInputFromSettings({
  id: "green",
  name: "Green",
  original_name: "Green",
  alias: "Green",
  url: "http://green:8096",
  enabled: true,
  notes: "",
  icon: "fa-server",
  icon_color: "#0f9d58",
  icon_style: "solid",
  api_key_configured: true,
});

describe("Emby server drafts", () => {
  it("adopts refreshed values when the editor has no local changes", () => {
    const incoming = { ...saved, alias: "Green 4K" };

    expect(refreshedEmbyServerDraft(saved, saved, incoming)).toEqual(incoming);
  });

  it("keeps a local draft when a refresh reports a different saved value", () => {
    const draft = { ...saved, notes: "Da verificare" };
    const incoming = { ...saved, alias: "Green 4K" };

    expect(refreshedEmbyServerDraft(draft, saved, incoming)).toEqual(draft);
  });
});
