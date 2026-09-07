function elementIsRendered(element: HTMLElement) {
  for (let current: HTMLElement | null = element; current; current = current.parentElement) {
    const style = window.getComputedStyle(current);
    if (style.display === "none" || style.visibility === "hidden") return false;
  }
  return true;
}

function focusFirstRendered(
  candidates: Iterable<HTMLElement>,
  fallback?: HTMLElement | null,
) {
  const target = Array.from(candidates).find(elementIsRendered) || fallback;
  target?.focus();
}

export { elementIsRendered, focusFirstRendered };
