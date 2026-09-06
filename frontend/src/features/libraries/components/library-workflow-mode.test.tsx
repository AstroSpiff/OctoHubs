import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { LibraryWorkflowMode } from "@/features/libraries/components/library-workflow-mode";
import { WorkspaceCapabilitiesProvider } from "@/features/session/workspace-capabilities";


describe("LibraryWorkflowMode capabilities", () => {
  it.each([
    [false, false],
    [true, true],
  ])("renders with canMutate=%s only when writable", (canMutate, visible) => {
    const markup = renderToStaticMarkup(
      <WorkspaceCapabilitiesProvider canMutate={canMutate}>
        <LibraryWorkflowMode enabled={false} onChange={() => undefined} />
      </WorkspaceCapabilitiesProvider>,
    );

    expect(markup.includes("Modalità Workflow Completo")).toBe(visible);
  });
});
