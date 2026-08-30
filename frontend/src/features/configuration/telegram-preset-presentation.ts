type TelegramAlertCheck = { status?: string; message?: string } | undefined;

type TelegramAlertPresentation = {
  label: string;
  severity: "ok" | "warning" | "error" | "unknown";
  detail: string;
};

function telegramAlertPresentation(check: TelegramAlertCheck): TelegramAlertPresentation {
  const status = String(check?.status || "").trim().toLowerCase();
  const detail = String(check?.message || "").trim();
  if (status === "admin" || status === "ok") return { label: "Bot admin", severity: "ok", detail: detail || "Bot amministratore" };
  if (status === "member" || status === "restricted") return { label: "Bot presente", severity: "warning", detail: detail || "Bot presente ma non amministratore" };
  if (status === "missing" || status === "left" || status === "kicked") return { label: "Bot assente", severity: "error", detail: detail || "Bot non presente" };
  if (status === "error") return { label: "Verifica fallita", severity: "error", detail: detail || "Verifica non riuscita" };
  if (status) return { label: "Da verificare", severity: "warning", detail: detail || `Stato: ${status}` };
  return { label: "Non verificato", severity: "unknown", detail: detail || "Nessuna verifica disponibile" };
}

export { telegramAlertPresentation };
export type { TelegramAlertPresentation };
