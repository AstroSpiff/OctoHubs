import { describe, expect, it } from "vitest";

import { lockDialogScroll } from "@/components/ui/dialog-scroll-lock";

function scrollTarget(overflow = "", paddingRight = "") {
  return { style: { overflow, paddingRight } };
}

describe("dialog scroll lock", () => {
  it("restores the page styles after the final dialog closes", () => {
    const target = scrollTarget("auto", "4px");
    const release = lockDialogScroll(target, {
      computedPaddingRight: 4,
      scrollbarWidth: 12,
    });

    expect(target.style).toEqual({ overflow: "hidden", paddingRight: "16px" });

    release();

    expect(target.style).toEqual({ overflow: "auto", paddingRight: "4px" });
  });

  it("keeps the page locked until stacked dialogs are all closed", () => {
    const target = scrollTarget();
    const releaseEditor = lockDialogScroll(target);
    const releaseConfirmation = lockDialogScroll(target);

    releaseConfirmation();
    expect(target.style.overflow).toBe("hidden");

    releaseEditor();
    expect(target.style.overflow).toBe("");
  });
});
