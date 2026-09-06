import { describe, expect, it } from "vitest";

import { userIconsTarget } from "@/features/user-icons/user-icons-navigation";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { UserIconManagementSection } from "@/features/user-icons/components/user-icon-management-section";

describe("user icons route", () => {
  it("uses the shared focus query so the management section is reached after lazy rendering", () => {
    expect(userIconsTarget).toBe("/users?focus=icon-management-card");
  });

  it("keeps the icon management target focusable for deep links", () => {
    const icons = {
      config: { data: undefined, dataUpdatedAt: 0, error: null, isFetching: false, refetch: () => Promise.resolve() },
      profile: { isPending: false, variables: undefined, error: null, mutate: () => undefined },
      removeProfile: { isPending: false, variables: undefined, error: null, mutate: () => undefined },
      binding: { isPending: false, variables: undefined, error: null, mutate: () => undefined },
      bindings: { isPending: false, variables: undefined, error: null, mutate: () => undefined },
      bindingOperations: { pendingKeys: new Set(), errors: {} },
      rule: { isPending: false, variables: undefined, error: null, mutate: () => undefined },
      removeRule: { isPending: false, variables: undefined, error: null, mutate: () => undefined },
      profileOperations: { pendingKeys: new Set(), errors: {} },
      ruleOperations: { pendingKeys: new Set(), errors: {} },
      refresh: () => Promise.resolve(),
    } as never;

    const markup = renderToStaticMarkup(
      createElement(UserIconManagementSection, { icons, servers: [] }),
    );

    expect(markup).toContain('id="icon-management-card"');
    expect(markup).toContain('tabindex="-1"');
    expect(markup).toContain('workspace-heading--subsection');
    expect(markup).toContain('id="icon-management-title"');
    expect(markup).toContain("Caricamento profili icona");
    expect(markup).not.toContain("Non ci sono ancora profili icona");
  });
});
