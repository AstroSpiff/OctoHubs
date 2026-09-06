import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { IconProfilesMatrix } from "@/features/user-icons/components/icon-profiles-matrix";
import { iconRuleOperationKey } from "@/features/user-icons/use-keyed-operation-state";

const profile = {
  id: "family",
  label: "Famiglia",
  is_group_profile: true,
};

describe("IconProfilesMatrix", () => {
  it("locks and reports only the image cell being changed", () => {
    const markup = renderToStaticMarkup(
      <IconProfilesMatrix
        config={{
          profiles: [profile],
        matrix: { family: { green: "icons/family-green.png", purple: "icons/family-purple.png" } },
          bindings: {},
        }}
        servers={[{ id: "green", name: "Green" }, { id: "purple", name: "Purple" }]}
        revision={3}
        pendingRuleKeys={new Set([
          iconRuleOperationKey("family", "green"),
          iconRuleOperationKey("family", "purple"),
        ])}
        ruleErrors={{
          [iconRuleOperationKey("family", "purple")]: "Caricamento non riuscito",
        }}
        onCreate={() => undefined}
        onEdit={() => undefined}
        onDeleteProfile={() => undefined}
        onUpload={() => undefined}
        onDeleteRule={() => undefined}
      />,
    );

    expect(markup).toContain('id="icon-file-family-green"');
    expect(markup).toContain('disabled=""');
    expect(markup).toContain('aria-disabled="true"');
    expect(markup).toContain('role="region"');
    expect(markup).toContain('tabindex="0"');
    expect(markup).toContain("Scorri orizzontalmente per vedere tutti i server.");
    expect(markup.match(/Operazione immagine in corso/g)).toHaveLength(2);
    expect(markup).toContain("Caricamento non riuscito");
  });
});
