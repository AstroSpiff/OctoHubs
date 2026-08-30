import { useEffect, useRef } from "react";
import type { ChangeEventHandler } from "react";

type ProbeSelectionCheckboxProps = {
  ariaLabel?: string;
  checked: boolean;
  indeterminate?: boolean;
  disabled?: boolean;
  onChange: ChangeEventHandler<HTMLInputElement>;
};

function ProbeSelectionCheckbox({
  ariaLabel,
  checked,
  indeterminate = false,
  disabled = false,
  onChange,
}: ProbeSelectionCheckboxProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (inputRef.current) inputRef.current.indeterminate = indeterminate;
  }, [indeterminate]);

  return (
    <input
      ref={inputRef}
      type="checkbox"
      checked={checked}
      disabled={disabled}
      aria-label={ariaLabel}
      aria-checked={indeterminate ? "mixed" : checked}
      onChange={onChange}
    />
  );
}

export { ProbeSelectionCheckbox };
