// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { BulkSettingsOverview } from "@/features/users/components/bulk-settings-overview";
import type { EmbyUser } from "@/features/users/types";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

const users: EmbyUser[] = [
  {
    server_id: "green",
    server_name: "Green",
    user_id: "anna",
    name: "Anna",
    is_disabled: false,
    is_user_disabled: false,
    is_remote_disabled: false,
    enable_remote_access: true,
    is_admin: false,
    is_leader: true,
  },
  {
    server_id: "purple",
    server_name: "Purple",
    server_alias: "Viola",
    user_id: "anna-purple",
    name: "Anna",
    is_disabled: false,
    is_user_disabled: false,
    is_remote_disabled: false,
    enable_remote_access: true,
    is_admin: false,
    is_leader: false,
  },
];

describe("BulkSettingsOverview", () => {
  let container: HTMLDivElement | null = null;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  });

  afterEach(() => {
    document.body.replaceChildren();
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
    container = null;
  });

  it("reports impact and keeps every selected destination identifiable", () => {
    container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);

    act(() => {
      root.render(
        <BulkSettingsOverview
          users={users}
          selectedFieldCount={2}
          applyLibraries
        />,
      );
    });

    expect(container.textContent).toContain("Utenti");
    expect(container.textContent).toContain("Campi");
    expect(container.textContent).toContain("Librerie");
    expect(container.textContent).toContain("Sì");
    expect(container.textContent).toContain("Green");
    expect(container.textContent).toContain("Viola");
  });
});
