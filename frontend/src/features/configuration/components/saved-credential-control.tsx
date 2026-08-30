function SavedCredentialControl({
  configured,
  pendingRemoval,
  label,
  disabled = false,
  onPendingRemovalChange,
}: {
  configured: boolean;
  pendingRemoval: boolean;
  label: string;
  disabled?: boolean;
  onPendingRemovalChange: (next: boolean) => void;
}) {
  if (!configured) return null;

  return <span className="saved-credential-control">
    <input
      type="checkbox"
      checked={pendingRemoval}
      disabled={disabled}
      aria-label={label}
      onChange={(event) => onPendingRemovalChange(event.target.checked)}
    />
    <span>{pendingRemoval ? "Rimozione al prossimo salvataggio" : label}</span>
  </span>;
}

export { SavedCredentialControl };
