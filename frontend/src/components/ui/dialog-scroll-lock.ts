type ScrollLockTarget = {
  style: {
    overflow: string;
    paddingRight: string;
  };
};

type ScrollLockOptions = {
  computedPaddingRight?: number;
  scrollbarWidth?: number;
};

type ScrollLockState = {
  count: number;
  overflow: string;
  paddingRight: string;
};

const scrollLocks = new WeakMap<ScrollLockTarget, ScrollLockState>();

function lockDialogScroll(
  target: ScrollLockTarget,
  { computedPaddingRight = 0, scrollbarWidth = 0 }: ScrollLockOptions = {},
): () => void {
  let state = scrollLocks.get(target);
  if (!state) {
    state = {
      count: 0,
      overflow: target.style.overflow,
      paddingRight: target.style.paddingRight,
    };
    scrollLocks.set(target, state);
  }

  if (state.count === 0) {
    target.style.overflow = "hidden";
    if (scrollbarWidth > 0) {
      target.style.paddingRight = `${computedPaddingRight + scrollbarWidth}px`;
    }
  }
  state.count += 1;

  let released = false;
  return () => {
    if (released) return;
    released = true;
    state.count -= 1;
    if (state.count > 0) return;

    target.style.overflow = state.overflow;
    target.style.paddingRight = state.paddingRight;
    scrollLocks.delete(target);
  };
}

function lockDocumentScroll(body: HTMLElement): () => void {
  const documentElement = body.ownerDocument.documentElement;
  const viewport = body.ownerDocument.defaultView;
  const computedPaddingRight = Number.parseFloat(
    viewport?.getComputedStyle(body).paddingRight || "0",
  );
  const scrollbarWidth = Math.max(
    0,
    (viewport?.innerWidth || 0) - documentElement.clientWidth,
  );

  return lockDialogScroll(body, {
    computedPaddingRight: Number.isFinite(computedPaddingRight)
      ? computedPaddingRight
      : 0,
    scrollbarWidth,
  });
}

export { lockDialogScroll, lockDocumentScroll };
