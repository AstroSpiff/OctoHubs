import { describe, expect, it } from "vitest";

import {
  lockDialogScroll,
  scrollLockClass,
} from "@/components/ui/dialog-scroll-lock";

function scrollTarget(initial: string[] = []) {
  const classes = new Set(initial);
  return {
    classes,
    classList: {
      add: (value: string) => classes.add(value),
      contains: (value: string) => classes.has(value),
      remove: (value: string) => classes.delete(value),
    } as unknown as DOMTokenList,
  };
}

describe("dialog scroll lock", () => {
  it("restores the page class after the final dialog closes", () => {
    const target = scrollTarget();
    const release = lockDialogScroll(target);

    expect(target.classes.has(scrollLockClass)).toBe(true);

    release();

    expect(target.classes.has(scrollLockClass)).toBe(false);
  });

  it("keeps the page locked until stacked dialogs are all closed", () => {
    const target = scrollTarget();
    const releaseEditor = lockDialogScroll(target);
    const releaseConfirmation = lockDialogScroll(target);

    releaseConfirmation();
    expect(target.classes.has(scrollLockClass)).toBe(true);

    releaseEditor();
    expect(target.classes.has(scrollLockClass)).toBe(false);
  });

  it("preserves a lock class owned by another subsystem", () => {
    const target = scrollTarget([scrollLockClass]);
    const release = lockDialogScroll(target);

    release();

    expect(target.classes.has(scrollLockClass)).toBe(true);
  });
});
