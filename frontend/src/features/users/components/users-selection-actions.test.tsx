import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { WorkspaceCapabilitiesProvider } from "@/features/session/workspace-capabilities";
import { UsersSelectionActions } from "@/features/users/components/users-selection-actions";

const callbacks = {
  onLink: () => undefined,
  onBulkSettings: () => undefined,
  onBulkClone: () => undefined,
  onDeselect: () => undefined,
};

describe("UsersSelectionActions", () => {
  it("does not expose stale bulk actions to a viewer", () => {
    const markup = renderToStaticMarkup(
      <WorkspaceCapabilitiesProvider canMutate={false}>
        <UsersSelectionActions selectedCount={2} hiddenCount={0} {...callbacks} />
      </WorkspaceCapabilitiesProvider>,
    );

    expect(markup).toBe("");
  });
});
