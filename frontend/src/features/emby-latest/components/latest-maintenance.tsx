import { DatabaseZap, History, Trash2 } from "@/components/ui/icons";

import { Button } from "@/components/ui/button";

function LatestMaintenance({
  resetting,
  clearing,
  clearingScans,
  onReset,
  onClearState,
  onClearScans,
}: {
  resetting: boolean;
  clearing: boolean;
  clearingScans: boolean;
  onReset: () => void;
  onClearState: () => void;
  onClearScans: () => void;
}) {
  const busy = resetting || clearing || clearingScans;

  return (
    <section className="latest-config-card latest-maintenance">
      <header>
        <h4>Manutenzione</h4>
        <p>
          Interventi sui dati persistiti. Preset e regole non vengono rimossi.
        </p>
      </header>
      <div>
        <p>Reset completo delle pubblicazioni: STATE + CACHE.</p>
        <Button
          type="button"
          requiresWriteAccess
          variant="danger"
          size="compact"
          onClick={onReset}
          disabled={busy}
        >
          <Trash2 size={15} aria-hidden="true" />
          Reset totale pubblicazioni
        </Button>
      </div>
      <div>
        <p>
          Azzera il tracking delle notifiche mantenendo cache, preset e regole.
        </p>
        <Button
          type="button"
          requiresWriteAccess
          variant="danger"
          size="compact"
          onClick={onClearState}
          disabled={busy}
        >
          <History size={15} aria-hidden="true" />
          Azzera STATE pubblicazioni
        </Button>
      </div>
      <div>
        <p>
          Rimuovi i record persistiti per scansione e aggiornamenti metadata.
        </p>
        <Button
          type="button"
          requiresWriteAccess
          variant="danger"
          size="compact"
          onClick={onClearScans}
          disabled={busy}
        >
          <DatabaseZap size={15} aria-hidden="true" />
          Pulisci dati scan/metadata
        </Button>
      </div>
      {busy ? (
        <p className="latest-form-status" role="status">
          Manutenzione pubblicazioni in corso...
        </p>
      ) : null}
    </section>
  );
}

export { LatestMaintenance };
