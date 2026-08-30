import { useEffect } from "react";

function deepLinkFocusId(search: string): string {
  return new URLSearchParams(search).get("focus")?.trim() || "";
}

function useDeepLinkFocus(search: string) {
  const targetId = deepLinkFocusId(search);

  useEffect(() => {
    if (!targetId) return;

    let cancelled = false;
    let timeout = 0;
    let highlightTimeout = 0;
    let focusedTarget: HTMLElement | null = null;
    const observer = new MutationObserver(moveToTarget);

    function moveToTarget() {
      if (cancelled) return;
      const target = document.getElementById(targetId);
      if (!target) return;
      if (!(target instanceof HTMLElement)) return;

      observer.disconnect();
      window.clearTimeout(timeout);
      const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
      target.dataset.deepLinkFocus = "true";
      target.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" });
      target.focus({ preventScroll: true });
      focusedTarget = target;
      highlightTimeout = window.setTimeout(() => {
        target.removeAttribute("data-deep-link-focus");
      }, 2_400);
    }

    observer.observe(document.body, { childList: true, subtree: true });
    window.requestAnimationFrame(moveToTarget);
    timeout = window.setTimeout(() => observer.disconnect(), 10_000);
    return () => {
      cancelled = true;
      observer.disconnect();
      window.clearTimeout(timeout);
      window.clearTimeout(highlightTimeout);
      focusedTarget?.removeAttribute("data-deep-link-focus");
    };
  }, [targetId]);
}

export { deepLinkFocusId, useDeepLinkFocus };
