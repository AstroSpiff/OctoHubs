import {
  useCallback,
  useEffect,
  useRef,
  type MouseEvent,
  type ReactNode,
} from "react";

import { isTopmostDialog } from "@/components/ui/dialog-stack";
import { lockDocumentScroll } from "@/components/ui/dialog-scroll-lock";

type DialogBackdropProps = {
  children: ReactNode;
  className: string;
  dismissible?: boolean;
  onDismiss: () => void;
};

const focusableSelector = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

function DialogBackdrop({
  children,
  className,
  dismissible = true,
  onDismiss,
}: DialogBackdropProps) {
  const backdropRef = useRef<HTMLDivElement>(null);
  const dismissRef = useRef(onDismiss);
  const triggerRef = useRef<HTMLElement | null>(null);

  dismissRef.current = onDismiss;

  const activeDialog = useCallback(() => {
    return (
      backdropRef.current?.querySelector<HTMLElement>(
        '[role="dialog"][aria-modal="true"], [role="alertdialog"][aria-modal="true"]',
      ) || null
    );
  }, []);

  const focusableElements = useCallback(() => {
    return Array.from(
      activeDialog()?.querySelectorAll<HTMLElement>(focusableSelector) || [],
    ).filter(
      (element) =>
        element.getAttribute("aria-hidden") !== "true" && element.tabIndex >= 0,
    );
  }, [activeDialog]);

  useEffect(() => {
    triggerRef.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;

    const frame = window.requestAnimationFrame(() => {
      focusableElements()[0]?.focus();
    });

    return () => {
      window.cancelAnimationFrame(frame);
      if (triggerRef.current?.isConnected) triggerRef.current.focus();
    };
  }, [focusableElements]);

  useEffect(() => lockDocumentScroll(document.body), []);

  useEffect(() => {
    const handleKeyboard = (event: KeyboardEvent) => {
      const backdrop = backdropRef.current;
      const dialogBackdrops = Array.from(
        document.querySelectorAll<HTMLDivElement>(
          "[data-octohubs-dialog-backdrop]",
        ),
      );
      if (!isTopmostDialog(dialogBackdrops, backdrop)) return;

      if (event.key === "Escape" && dismissible) {
        event.preventDefault();
        dismissRef.current();
        return;
      }

      if (event.key !== "Tab") return;
      const focusable = focusableElements();
      if (!focusable.length) return;

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleKeyboard);
    return () => document.removeEventListener("keydown", handleKeyboard);
  }, [dismissible, focusableElements]);

  function dismissOnBackdrop(event: MouseEvent<HTMLDivElement>) {
    if (dismissible && event.target === event.currentTarget) onDismiss();
  }

  return (
    <div
      ref={backdropRef}
      className={className}
      data-octohubs-dialog-backdrop="true"
      role="presentation"
      onMouseDown={dismissOnBackdrop}
    >
      {children}
    </div>
  );
}

export { DialogBackdrop };
