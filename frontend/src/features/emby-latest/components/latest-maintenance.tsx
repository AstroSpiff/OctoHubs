import { History, Trash2 } from "@/components/ui/icons";

import { Button } from "@/components/ui/button";

function LatestMaintenanceAction({
  action,
  busy,
  description,
  icon,
  status,
  title,
}: {
  action: { label: string; onClick: () => void };
  busy: boolean;
  description: string;
  icon: "history" | "trash";
  status: string;
  title: string;
}) {
  return (
    <section className="latest-config-card latest-maintenance">
      <header>
        <h4>{title}</h4>
      </header>
      <div>
        <p>{description}</p>
        <Button
          type="button"
          requiresWriteAccess
          variant="danger"
          size="compact"
          onClick={action.onClick}
          disabled={busy}
        >
          {icon === "trash" ? (
            <Trash2 size={15} aria-hidden="true" />
          ) : (
            <History size={15} aria-hidden="true" />
          )}
          {action.label}
        </Button>
      </div>
      {busy ? (
        <p className="latest-form-status" role="status">
          {status}
        </p>
      ) : null}
    </section>
  );
}

function LatestPublicationsMaintenance({
  resetting,
  onReset,
}: {
  resetting: boolean;
  onReset: () => void;
}) {
  return (
    <LatestMaintenanceAction
      title="Manutenzione pubblicazioni"
      description="Cancella i dati salvati e li ricostruisce al prossimo aggiornamento. Gli elementi già inviati potrebbero tornare notificabili."
      action={{ label: "Ricostruisci pubblicazioni", onClick: onReset }}
      icon="trash"
      busy={resetting}
      status="Ricostruzione pubblicazioni in corso..."
    />
  );
}

function LatestNotificationsMaintenance({
  clearing,
  onClearState,
}: {
  clearing: boolean;
  onClearState: () => void;
}) {
  return (
    <LatestMaintenanceAction
      title="Manutenzione notifiche"
      description="Dimentica quali pubblicazioni risultano già inviate. Il prossimo invio potrebbe ripeterle; preset e regole restano invariati."
      action={{ label: "Reimposta notifiche inviate", onClick: onClearState }}
      icon="history"
      busy={clearing}
      status="Reimpostazione notifiche in corso..."
    />
  );
}

export { LatestNotificationsMaintenance, LatestPublicationsMaintenance };
