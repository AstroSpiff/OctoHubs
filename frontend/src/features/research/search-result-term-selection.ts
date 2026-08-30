import type { MouseEvent as ReactMouseEvent } from "react";

export function selectedResultTerm(
  element: HTMLElement,
  event: ReactMouseEvent<HTMLElement>,
): string {
  const selected = window.getSelection()?.toString().trim() || "";
  if (selected && selected.length <= 120) return selected;
  const documentWithCaret = document as Document & {
    caretPositionFromPoint?: (
      horizontal: number,
      vertical: number,
    ) => { offsetNode: Node; offset: number } | null;
    caretRangeFromPoint?: (
      horizontal: number,
      vertical: number,
    ) => Range | null;
  };
  const position = documentWithCaret.caretPositionFromPoint?.(
    event.clientX,
    event.clientY,
  );
  const range = position
    ? null
    : documentWithCaret.caretRangeFromPoint?.(event.clientX, event.clientY);
  const node = position?.offsetNode || range?.startContainer;
  const offset = position?.offset ?? range?.startOffset;
  if (
    !node ||
    typeof offset !== "number" ||
    !element.contains(node) ||
    node.nodeType !== Node.TEXT_NODE
  ) {
    return "";
  }
  const text = node.textContent || "";
  const valid = /[a-zA-Z0-9]/;
  let start = offset;
  let end = offset;
  while (start > 0 && valid.test(text[start - 1])) start -= 1;
  while (end < text.length && valid.test(text[end])) end += 1;
  return text.slice(start, end).trim();
}
