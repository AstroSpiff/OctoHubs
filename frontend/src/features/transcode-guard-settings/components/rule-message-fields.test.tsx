import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { RuleMessageFields } from "@/features/transcode-guard-settings/components/rule-message-fields";
import { createGuardRule } from "@/features/transcode-guard-settings/rule-model";

describe("RuleMessageFields", () => {
  it("keeps the message title editable for temporary warnings", () => {
    const markup = renderToStaticMarkup(
      <RuleMessageFields rule={{ ...createGuardRule(), mode: "warn", message_display_mode: "toast" }} onChange={() => undefined} />,
    );

    expect(markup).toMatch(/Titolo messaggio<\/span><input(?![^>]*disabled)/);
  });
});
