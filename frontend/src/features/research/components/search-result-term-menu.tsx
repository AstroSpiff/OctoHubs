import {
  type KeyboardEvent,
  type Ref,
  useEffect,
  useRef,
  useState,
} from "react";

import type { SearchResultActionNotice } from "@/features/research/components/search-result-actions";
import type { RequestRuleTermField } from "@/features/research/request-search-rules";
import { WriteAction } from "@/features/session/workspace-capabilities";

type SearchResultTermMenuPosition = { term: string; x: number; y: number };
type AddTermAction = (
  term: string,
  field: RequestRuleTermField,
) => Promise<string>;

type SearchResultTermMenuProps = {
  menu: SearchResultTermMenuPosition | null;
  menuRef?: Ref<HTMLDivElement>;
  onAddTerm?: AddTermAction;
  onNotice: (notice: SearchResultActionNotice) => void;
  onClose: () => void;
};

function SearchResultTermMenu({
  menu,
  menuRef,
  onAddTerm,
  onNotice,
  onClose,
}: SearchResultTermMenuProps) {
  const [adding, setAdding] = useState(false);
  const menuItemsRef = useRef<Array<HTMLButtonElement | null>>([]);

  useEffect(() => {
    if (!menu || !onAddTerm) return undefined;

    const focusFirstAction = window.requestAnimationFrame(() => {
      menuItemsRef.current[0]?.focus();
    });
    return () => window.cancelAnimationFrame(focusFirstAction);
  }, [menu, onAddTerm]);

  async function apply(field: RequestRuleTermField) {
    if (!menu || !onAddTerm) return;
    const term = menu.term;
    onClose();
    setAdding(true);
    try {
      onNotice({ message: await onAddTerm(term, field), tone: "success" });
    } catch (reason) {
      onNotice({
        message:
          reason instanceof Error
            ? reason.message
            : "Aggiornamento della regola non riuscito.",
        tone: "error",
      });
    } finally {
      setAdding(false);
    }
  }

  if (!menu || !onAddTerm) return null;

  function focusMenuItem(index: number) {
    const items = menuItemsRef.current.filter(
      (item): item is HTMLButtonElement => item !== null && !item.disabled,
    );
    if (!items.length) return;
    items[(index + items.length) % items.length]?.focus();
  }

  function handleMenuKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const items = menuItemsRef.current.filter(
      (item): item is HTMLButtonElement => item !== null && !item.disabled,
    );
    const currentIndex = items.indexOf(event.target as HTMLButtonElement);
    if (currentIndex < 0) return;

    if (event.key === "ArrowDown") {
      event.preventDefault();
      focusMenuItem(currentIndex + 1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      focusMenuItem(currentIndex - 1);
    } else if (event.key === "Home") {
      event.preventDefault();
      focusMenuItem(0);
    } else if (event.key === "End") {
      event.preventDefault();
      focusMenuItem(items.length - 1);
    }
  }

  return (
    <WriteAction>
      <div
        className="research-term-menu"
        ref={menuRef}
        aria-label={`Azioni per ${menu.term}`}
        role="menu"
        style={{ left: menu.x, top: menu.y }}
        onKeyDown={handleMenuKeyDown}
      >
        <strong>{menu.term}</strong>
        <button
          type="button"
          role="menuitem"
          ref={(element) => {
            menuItemsRef.current[0] = element;
          }}
          disabled={adding}
          onClick={() => void apply("query_terms")}
        >
          Aggiungi a termini query
        </button>
        <button
          type="button"
          role="menuitem"
          ref={(element) => {
            menuItemsRef.current[1] = element;
          }}
          disabled={adding}
          onClick={() => void apply("filter_terms")}
        >
          Aggiungi a termini filtrati
        </button>
        <button
          type="button"
          role="menuitem"
          ref={(element) => {
            menuItemsRef.current[2] = element;
          }}
          disabled={adding}
          onClick={() => void apply("exclude_terms")}
        >
          Aggiungi a termini esclusi
        </button>
      </div>
    </WriteAction>
  );
}

export { SearchResultTermMenu };
export type { AddTermAction, SearchResultTermMenuPosition };
