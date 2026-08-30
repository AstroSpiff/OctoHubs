import { StatusBadge } from "@/components/ui/badge";
import { formatUserTime, syncPresentation } from "@/features/users/presentation";
import type { EmbyUserGroup } from "@/features/users/types";

type GroupSyncStatusProps = {
  group: EmbyUserGroup;
  className?: string;
};

function GroupSyncStatus({ group, className }: GroupSyncStatusProps) {
  const status = syncPresentation(group);

  return (
    <div className={`users-group-sync-status${className ? ` ${className}` : ""}`}>
      <StatusBadge severity={status.severity}>{status.label}</StatusBadge>
      <span>
        {group.last_sync_at
          ? `Ultima sincronizzazione: ${formatUserTime(group.last_sync_at)}`
          : "Mai sincronizzato"}
      </span>
      {group.last_sync_message ? <small>{group.last_sync_message}</small> : null}
    </div>
  );
}

export { GroupSyncStatus };
