import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type SyntheticEvent,
} from "react";

function usePopoverDisclosure() {
  const detailsRef = useRef<HTMLDetailsElement>(null);
  const summaryRef = useRef<HTMLElement>(null);
  const contentId = useId();
  const [open, setOpen] = useState(false);

  const close = useCallback((restoreFocus = false) => {
    const details = detailsRef.current;
    if (!details?.open) return;
    details.open = false;
    setOpen(false);
    if (restoreFocus) {
      window.requestAnimationFrame(() => summaryRef.current?.focus());
    }
  }, []);

  const onToggle = useCallback(
    (event: SyntheticEvent<HTMLDetailsElement>) => {
      setOpen(event.currentTarget.open);
    },
    [],
  );

  useEffect(() => {
    if (!open) return undefined;

    const dismissOnPointerDown = (event: PointerEvent) => {
      if (
        event.target instanceof Node &&
        !detailsRef.current?.contains(event.target)
      ) {
        close();
      }
    };
    const dismissOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      close(true);
    };

    document.addEventListener("pointerdown", dismissOnPointerDown);
    document.addEventListener("keydown", dismissOnEscape);
    return () => {
      document.removeEventListener("pointerdown", dismissOnPointerDown);
      document.removeEventListener("keydown", dismissOnEscape);
    };
  }, [close, open]);

  return { contentId, detailsRef, summaryRef, open, close, onToggle };
}

export { usePopoverDisclosure };
