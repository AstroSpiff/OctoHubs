import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { IconProfilesMatrix } from "@/features/user-icons/components/icon-profiles-matrix";

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
          matrix: { family: { green: "icons/family-green.png" } },
          bindings: {},
        }}
        servers={[{ id: "green", name: "Green" }]}
        revision={3}
        changingRule={{ profileId: "family", serverId: "green" }}
        ruleError={() => "Caricamento non riuscito"}
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
    expect(markup).toContain("Operazione immagine in corso");
    expect(markup).toContain("Caricamento non riuscito");
  });
});
