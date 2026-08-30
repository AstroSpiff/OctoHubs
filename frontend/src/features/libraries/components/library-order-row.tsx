import { ArrowDown, ArrowUp, GripVertical } from "@/components/ui/icons";

import { Button } from "@/components/ui/button";

type LibraryOrderRowProps = {
  label: string;
  secondary?: string;
  index: number;
  total: number;
  disabled: boolean;
  dragging: boolean;
  onMove: (direction: -1 | 1) => void;
  onDragStart: () => void;
  onDrop: (after: boolean) => void;
  onDragEnd: () => void;
};

function LibraryOrderRow({
  label,
  secondary,
  index,
  total,
  disabled,
  dragging,
  onMove,
  onDragStart,
  onDrop,
  onDragEnd,
}: LibraryOrderRowProps) {
  return (
    <div
      className={`library-order-row${dragging ? " is-dragging" : ""}${disabled ? " is-disabled" : ""}`}
      role="listitem"
      draggable={!disabled}
      onDragStart={(event) => {
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", label);
        onDragStart();
      }}
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => {
        event.preventDefault();
        const bounds = event.currentTarget.getBoundingClientRect();
        onDrop(event.clientY > bounds.top + bounds.height / 2);
      }}
      onDragEnd={onDragEnd}
    >
      <div>
        <strong><GripVertical size={15} aria-hidden="true" />{label}</strong>
        {secondary ? <small>{secondary}</small> : null}
      </div>
      <div className="library-order-row-actions">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          title={`Sposta ${label} in alto`}
          aria-label={`Sposta ${label} in alto`}
          disabled={disabled || index === 0}
          onClick={() => onMove(-1)}
        >
          <ArrowUp size={16} aria-hidden="true" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          title={`Sposta ${label} in basso`}
          aria-label={`Sposta ${label} in basso`}
          disabled={disabled || index === total - 1}
          onClick={() => onMove(1)}
        >
          <ArrowDown size={16} aria-hidden="true" />
        </Button>
      </div>
    </div>
  );
}

export { LibraryOrderRow };
