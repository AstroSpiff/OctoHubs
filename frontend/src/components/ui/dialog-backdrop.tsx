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

function isVisibleFocusable(element: HTMLElement, dialog: HTMLElement | null) {
  for (let current: HTMLElement | null = element; current && current !== dialog; current = current.parentElement) {
    if (current.hidden || current.hasAttribute("inert") || current.getAttribute("aria-hidden") === "true") {
      return false;
    }
    const style = window.getComputedStyle(current);
    if (style.display === "none" || style.visibility === "hidden") return false;
  }
  return element.tabIndex >= 0;
}

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
    const dialog = activeDialog();
    return Array.from(
      dialog?.querySelectorAll<HTMLElement>(focusableSelector) || [],
    ).filter((element) => isVisibleFocusable(element, dialog));
  }, [activeDialog]);

  const focusDialog = useCallback(() => {
    const dialog = activeDialog();
    if (!dialog) return;
    if (!dialog.hasAttribute("tabindex")) dialog.setAttribute("tabindex", "-1");
    dialog.focus();
  }, [activeDialog]);

  useEffect(() => {
    triggerRef.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;

    const frame = window.requestAnimationFrame(() => {
      const first = focusableElements()[0];
      if (first) first.focus();
      else focusDialog();
    });

    return () => {
      window.cancelAnimationFrame(frame);
      if (triggerRef.current?.isConnected) triggerRef.current.focus();
    };
  }, [focusDialog, focusableElements]);

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
      if (!focusable.length) {
        event.preventDefault();
        focusDialog();
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const dialog = activeDialog();
      if (!dialog?.contains(document.activeElement)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleKeyboard);
    return () => document.removeEventListener("keydown", handleKeyboard);
  }, [activeDialog, dismissible, focusDialog, focusableElements]);

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
