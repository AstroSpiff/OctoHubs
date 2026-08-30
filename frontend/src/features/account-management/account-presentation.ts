import type { AccountRole, ApiToken, ApiTokenPermissionProfileId, ApiTokenScope } from "@/features/account-management/types";
import type { NavigationPreferences } from "@/features/navigation/navigation-preferences";

const accountRoleLabels: Record<AccountRole, string> = {
  admin: "Amministratore",
  user: "Operatore",
  viewer: "Sola lettura",
};

const apiTokenScopeLabels: Record<ApiTokenScope, string> = {
  "read:status": "Legge stato",
  "read:account": "Legge il proprio account",
  "read:servers": "Legge server",
  "read:streams": "Legge stream",
  "read:users": "Legge utenti",
  "read:collections": "Legge collezioni",
  "read:libraries": "Legge librerie",
  "read:research": "Legge ricerca",
  "read:publications": "Legge pubblicazioni",
  "read:configuration": "Legge configurazione",
  "write:configuration": "Modifica configurazione",
  "write:account": "Modifica il proprio account",
  "manage:tokens": "Gestisce i propri token",
  "admin:accounts": "Gestisce gli account",
  "read:event_bridge": "Legge Event Bridge",
  "write:event_bridge": "Modifica Event Bridge",
  "write:transcode_guard": "Modifica Transcode Guard",
  "write:users": "Modifica utenti",
  "write:collections": "Modifica collezioni",
  "write:libraries": "Modifica librerie",
  "write:research": "Modifica ricerca",
  "write:publications": "Modifica pubblicazioni",
  "run:operations": "Esegue operazioni",
  "admin:all": "Amministrazione completa",
};

const apiTokenPermissionProfileLabels: Record<ApiTokenPermissionProfileId, string> = {
  read_only: "Sola lettura",
  operator: "Operatore",
  administrator: "Amministratore",
};

function navigationPreferenceLabels(preferences: NavigationPreferences) {
  return {
    primary: preferences.primary_navigation === "sidebar" ? "A sinistra" : "In alto",
    secondary: preferences.secondary_navigation === "sidebar" ? "Aside contestuale" : "Tab orizzontali",
  };
}

function formatAccountDate(value: string | null) {
  if (!value) return "Mai";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Non disponibile";
  return new Intl.DateTimeFormat("it-IT", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function formatApiTokenAction(action: ApiToken["last_action"]) {
  if (!action) return "Nessuna azione registrata";
  const labels: Record<string, string> = {
    api_token_read: "Lettura",
    api_token_write: "Modifica",
    api_token_operation: "Operazione",
    api_token_denied: "Rifiutato",
  };
  const label = labels[action.action] || "Azione";
  const scopeLabel = apiTokenScopeLabels[action.required_scope as ApiTokenScope] || action.required_scope || "scope non disponibile";
  const target = [action.method, action.path].filter(Boolean).join(" ");
  return `${label}: ${target || "endpoint non disponibile"} · ${scopeLabel} · ${formatAccountDate(action.at)}`;
}

export { accountRoleLabels, apiTokenPermissionProfileLabels, apiTokenScopeLabels, formatAccountDate, formatApiTokenAction, navigationPreferenceLabels };
