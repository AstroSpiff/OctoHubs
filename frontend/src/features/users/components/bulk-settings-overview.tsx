import { ServerIdentity } from "@/features/users/components/server-identity";
import type { EmbyUser } from "@/features/users/types";

type BulkSettingsOverviewProps = {
  users: EmbyUser[];
  selectedFieldCount: number;
  applyLibraries: boolean;
};

function BulkSettingsOverview({
  users,
  selectedFieldCount,
  applyLibraries,
}: BulkSettingsOverviewProps) {
  const userLabel = users.length === 1 ? "Utente" : "Utenti";
  const fieldLabel = selectedFieldCount === 1 ? "Campo" : "Campi";

  return (
    <section className="bulk-settings-overview" aria-label="Riepilogo applicazione impostazioni">
      <dl className="bulk-settings-overview-metrics">
        <div>
          <dt>{userLabel}</dt>
          <dd>{users.length}</dd>
        </div>
        <div>
          <dt>{fieldLabel}</dt>
          <dd>{selectedFieldCount}</dd>
        </div>
        <div>
          <dt>Librerie</dt>
          <dd>{applyLibraries ? "Sì" : "No"}</dd>
        </div>
      </dl>
      <div className="bulk-settings-targets">
        <span>Destinatari</span>
        <ul>
          {users.map((user) => (
            <li key={`${user.server_id}:${user.user_id}`}>
              <strong>{user.name}</strong>
              <ServerIdentity
                name={user.server_alias || user.server_name}
                icon={user.server_icon}
                color={user.server_icon_color}
                iconStyle={user.server_icon_style}
                size={11}
              />
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

export { BulkSettingsOverview };
