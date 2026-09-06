import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { WorkspaceCapabilitiesProvider } from "@/features/session/workspace-capabilities";
import { SystemStatusSection } from "@/features/system-status/components/status-presentation";
import type { SystemSection } from "@/features/system-status/types";

const section: SystemSection = {
  id: "services",
  title: "Integrazioni",
  severity: "ok",
  status_code: "ok",
  status_label: "OK",
  check_label: "Verifica integrazioni/server",
  href: "",
  refresh_interval_seconds: 30,
  items: [],
};

function renderSection(canMutate: boolean) {
  return renderToStaticMarkup(
    <WorkspaceCapabilitiesProvider canMutate={canMutate}>
      <SystemStatusSection
        section={section}
        onRefresh={() => undefined}
        refreshing={false}
      />
    </WorkspaceCapabilitiesProvider>,
  );
}

describe("system status mutation capabilities", () => {
  it("keeps read-only refresh but hides the integration check from viewers", () => {
    const markup = renderSection(false);

    expect(markup).toContain("Aggiorna area");
    expect(markup).not.toContain("Verifica integrazioni/server");
  });

  it("shows the integration check to editors", () => {
    expect(renderSection(true)).toContain("Verifica integrazioni/server");
  });
});
