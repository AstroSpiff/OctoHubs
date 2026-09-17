type ScrollLockTarget = Pick<HTMLElement, "classList">;

type ScrollLockState = {
  count: number;
  alreadyLocked: boolean;
};

const scrollLockClass = "is-dialog-scroll-locked";
const scrollLocks = new WeakMap<ScrollLockTarget, ScrollLockState>();

function lockDialogScroll(target: ScrollLockTarget): () => void {
  let state = scrollLocks.get(target);
  if (!state) {
    state = {
      alreadyLocked: target.classList.contains(scrollLockClass),
      count: 0,
    };
    scrollLocks.set(target, state);
  }

  if (state.count === 0) target.classList.add(scrollLockClass);
  state.count += 1;

  let released = false;
  return () => {
    if (released) return;
    released = true;
    state.count -= 1;
    if (state.count > 0) return;

    if (!state.alreadyLocked) target.classList.remove(scrollLockClass);
    scrollLocks.delete(target);
  };
}

function lockDocumentScroll(body: HTMLElement): () => void {
  return lockDialogScroll(body);
}

export { lockDialogScroll, lockDocumentScroll, scrollLockClass };
