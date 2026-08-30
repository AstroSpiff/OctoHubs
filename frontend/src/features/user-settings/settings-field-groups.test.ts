import { describe, expect, it } from "vitest";

import { groupSettingsFields } from "@/features/user-settings/settings-field-groups";

describe("settings field groups", () => {
  it("preserves schema order while separating contiguous group headings", () => {
    expect(groupSettingsFields([
      { key: "one", group: "Riproduzione" },
      { key: "two", group: "Riproduzione" },
      { key: "three", group: "Download" },
      { key: "four", group: "Riproduzione" },
    ])).toEqual([
      { label: "Riproduzione", fields: [{ key: "one", group: "Riproduzione" }, { key: "two", group: "Riproduzione" }] },
      { label: "Download", fields: [{ key: "three", group: "Download" }] },
      { label: "Riproduzione", fields: [{ key: "four", group: "Riproduzione" }] },
    ]);
  });
});
