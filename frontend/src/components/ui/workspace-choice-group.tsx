import type { KeyboardEvent, ReactNode } from "react";

import { tabAtKey } from "@/components/ui/tab-navigation";
import { cn } from "@/lib/utils";

type WorkspaceChoice = {
  content: ReactNode;
  controls?: string;
  disabled?: boolean;
  id: string;
};

type WorkspaceChoiceGroupProps = {
  ariaLabel: string;
  className?: string;
  idPrefix: string;
  mode?: "pressed" | "tab";
  onChange: (id: string) => boolean | void | Promise<boolean | void>;
  options: readonly WorkspaceChoice[];
  value: string;
};

function WorkspaceChoiceGroup({
  ariaLabel,
  className,
  idPrefix,
  mode = "pressed",
  onChange,
  options,
  value,
}: WorkspaceChoiceGroupProps) {
  async function selectFromKeyboard(
    event: KeyboardEvent<HTMLButtonElement>,
    current: string,
  ) {
    const next = tabAtKey(
      options.map((option) => option.id),
      current,
      event.key,
    );
    if (!next) return;

    event.preventDefault();
    const accepted = await onChange(next);
    if (accepted === false) return;
    window.requestAnimationFrame(() => {
      document.getElementById(`${idPrefix}-${next}`)?.focus();
    });
  }

  return (
    <div
      className={cn("workspace-choice-group", className)}
      role={mode === "tab" ? "tablist" : "group"}
      aria-label={ariaLabel}
    >
      {options.map((option) => {
        const active = option.id === value;

        return (
          <button
            key={option.id}
            id={`${idPrefix}-${option.id}`}
            type="button"
            role={mode === "tab" ? "tab" : undefined}
            aria-controls={mode === "tab" ? option.controls : undefined}
            aria-pressed={mode === "pressed" ? active : undefined}
            aria-selected={mode === "tab" ? active : undefined}
            tabIndex={mode === "tab" && !active ? -1 : undefined}
            className={active ? "is-active" : undefined}
            disabled={option.disabled}
            onClick={() => void onChange(option.id)}
            onKeyDown={(event) => void selectFromKeyboard(event, option.id)}
          >
            {option.content}
          </button>
        );
      })}
    </div>
  );
}

export { WorkspaceChoiceGroup };
export type { WorkspaceChoice };
