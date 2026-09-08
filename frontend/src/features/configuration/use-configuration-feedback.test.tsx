// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { ConfigurationTabId } from "@/features/configuration/configuration-navigation";
import {
  useConfigurationFeedback,
  type ConfigurationFeedbackLease,
} from "@/features/configuration/use-configuration-feedback";
import { WorkspaceCapabilitiesProvider } from "@/features/session/workspace-capabilities";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

let feedback: ReturnType<typeof useConfigurationFeedback> | undefined;

function Harness({ tab }: { tab: ConfigurationTabId }) {
  feedback = useConfigurationFeedback(tab);
  return <div data-error={feedback.error} data-notice={feedback.notice} />;
}

describe("configuration feedback ownership", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    feedback = undefined;
    globalThis.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  function render(accountId: number, tab: ConfigurationTabId) {
    act(() => {
      root.render(
        <WorkspaceCapabilitiesProvider accountId={accountId} canMutate>
          <Harness tab={tab} />
        </WorkspaceCapabilitiesProvider>,
      );
    });
  }

  function output() {
    return container.querySelector("div")!;
  }

  it("rejects late success and failure after a tab changes", () => {
    render(1, "services");
    let servicesLease: ConfigurationFeedbackLease;
    act(() => { servicesLease = feedback!.begin()!; });

    render(1, "automations");
    expect(feedback!.publishNotice(servicesLease!, "Servizi salvati")).toBe(false);
    expect(feedback!.publishError(servicesLease!, "Errore servizi")).toBe(false);
    expect(output().dataset.notice).toBe("");
    expect(output().dataset.error).toBe("");
  });

  it("does not let A overwrite B or resurrect after A to B to A", () => {
    render(1, "services");
    let firstServicesLease: ConfigurationFeedbackLease;
    act(() => { firstServicesLease = feedback!.begin()!; });

    render(1, "automations");
    let automationsLease: ConfigurationFeedbackLease;
    act(() => { automationsLease = feedback!.begin()!; });
    act(() => {
      expect(feedback!.publishNotice(automationsLease!, "Automazioni salvate")).toBe(true);
    });
    act(() => {
      expect(feedback!.publishNotice(firstServicesLease!, "Servizi salvati")).toBe(false);
    });
    expect(output().dataset.notice).toBe("Automazioni salvate");

    render(1, "services");
    act(() => {
      expect(feedback!.publishNotice(firstServicesLease!, "Servizi salvati")).toBe(false);
    });
    expect(output().dataset.notice).toBe("");
  });

  it("does not let a stale immediate Services callback clear feedback in Automations", () => {
    render(1, "services");
    const staleServicesNotice = feedback!.publishImmediateNotice;

    render(1, "automations");
    act(() => {
      expect(feedback!.publishImmediateNotice("Automazioni salvate")).toBe(true);
    });
    act(() => {
      expect(staleServicesNotice("Trakt collegato")).toBe(false);
    });

    expect(output().dataset.notice).toBe("Automazioni salvate");
  });

  it("invalidates leases on account change and unmount", () => {
    render(1, "telegram");
    let lease: ConfigurationFeedbackLease;
    act(() => { lease = feedback!.begin()!; });

    render(2, "telegram");
    expect(feedback!.publishNotice(lease!, "Telegram aggiornato")).toBe(false);

    const staleFeedback = feedback!;
    let unmountedLease: ConfigurationFeedbackLease;
    act(() => { unmountedLease = staleFeedback.begin()!; });
    act(() => root.render(<></>));
    expect(staleFeedback.publishError(unmountedLease!, "Errore tardivo")).toBe(false);
  });
});
