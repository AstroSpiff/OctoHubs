import { PanelLeft, PanelTop, X } from "@/components/ui/icons";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { DialogBackdrop } from "@/components/ui/dialog-backdrop";
import type {
  NavigationPreferences,
  PrimaryNavigationMode,
  SecondaryNavigationMode,
} from "@/features/navigation/navigation-preferences";
import { cn } from "@/lib/utils";

type NavigationPreferencesDialogProps = {
  error: Error | null;
  isSaving: boolean;
  onClose: () => void;
  onUpdate: (preferences: Partial<NavigationPreferences>) => void;
  open: boolean;
  preferences: NavigationPreferences;
};

function NavigationPreferencesDialog({
  error,
  isSaving,
  onClose,
  onUpdate,
  open,
  preferences,
}: NavigationPreferencesDialogProps) {
  if (!open) return null;

  return (
    <DialogBackdrop className="navigation-preferences-backdrop" onDismiss={onClose}>
      <section
        className="navigation-preferences-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="navigation-preferences-title"
      >
        <header>
          <div>
            <h2 id="navigation-preferences-title" className="contextual-heading" title="Il tuo spazio di lavoro">Preferenze interfaccia</h2>
            <p>Queste scelte sono personali e restano uguali su tutti i browser con cui accedi a OctoHubs.</p>
          </div>
          <Button type="button" variant="ghost" size="icon" onClick={onClose} aria-label="Chiudi preferenze interfaccia" title="Chiudi">
            <X size={18} aria-hidden="true" />
          </Button>
        </header>

        <NavigationModeControl
          title="Menu principale"
          description="Scegli dove trovare le aree principali quando lavori su schermi ampi."
          value={preferences.primary_navigation}
          disabled={isSaving}
          onChange={(primary_navigation) => onUpdate({ primary_navigation })}
        />
        <SecondaryModeControl
          value={preferences.secondary_navigation}
          disabled={isSaving}
          onChange={(secondary_navigation) => onUpdate({ secondary_navigation })}
        />

        <footer>
          <span className={cn(error && "is-error")} role="status" aria-live="polite">
            {error ? error.message : isSaving ? "Salvataggio in corso..." : "Preferenze salvate nel tuo profilo."}
          </span>
          <Button type="button" variant="secondary" onClick={onClose}>Chiudi</Button>
        </footer>
      </section>
    </DialogBackdrop>
  );
}

function NavigationModeControl({
  title,
  description,
  value,
  disabled,
  onChange,
}: {
  title: string;
  description: string;
  value: PrimaryNavigationMode;
  disabled: boolean;
  onChange: (value: PrimaryNavigationMode) => void;
}) {
  return (
    <section className="navigation-preferences-section" aria-labelledby="primary-navigation-mode-title">
      <div>
        <h3 id="primary-navigation-mode-title">{title}</h3>
        <p>{description}</p>
      </div>
      <div className="navigation-mode-options" role="group" aria-label={title}>
        <NavigationModeButton icon={<PanelTop size={18} aria-hidden="true" />} label="In alto" detail="Più spazio per i contenuti" active={value === "top"} disabled={disabled} onClick={() => onChange("top")} />
        <NavigationModeButton icon={<PanelLeft size={18} aria-hidden="true" />} label="A sinistra" detail="Voci sempre visibili" active={value === "sidebar"} disabled={disabled} onClick={() => onChange("sidebar")} />
      </div>
    </section>
  );
}

function SecondaryModeControl({ value, disabled, onChange }: { value: SecondaryNavigationMode; disabled: boolean; onChange: (value: SecondaryNavigationMode) => void }) {
  return (
    <section className="navigation-preferences-section" aria-labelledby="secondary-navigation-mode-title">
      <div>
        <h3 id="secondary-navigation-mode-title">Menu secondario</h3>
        <p>Organizza le sottosezioni di Ricerca, Emby Toolkit, Media Probe e Configurazione con tab oppure direttamente sotto la voce principale attiva. Su mobile restano sempre in tab.</p>
      </div>
      <div className="navigation-mode-options" role="group" aria-label="Menu secondario">
        <NavigationModeButton icon={<PanelTop size={18} aria-hidden="true" />} label="Tab" detail="Orizzontali sopra il contenuto" active={value === "tabs"} disabled={disabled} onClick={() => onChange("tabs")} />
        <NavigationModeButton icon={<PanelLeft size={18} aria-hidden="true" />} label="Sottomenu" detail="Sotto la voce principale" active={value === "sidebar"} disabled={disabled} onClick={() => onChange("sidebar")} />
      </div>
    </section>
  );
}

function NavigationModeButton({ active, detail, disabled, icon, label, onClick }: { active: boolean; detail: string; disabled: boolean; icon: ReactNode; label: string; onClick: () => void }) {
  return (
    <button type="button" className={cn("navigation-mode-option", active && "is-active")} aria-pressed={active} disabled={disabled} onClick={onClick}>
      {icon}
      <span><strong>{label}</strong><small>{detail}</small></span>
    </button>
  );
}

export { NavigationPreferencesDialog };
