const roleLabels: Record<string, string> = {
  admin: "Amministratore",
  user: "Utente",
  viewer: "Sola lettura",
};

function sessionRoleLabel(role?: string | null): string {
  const normalized = role?.trim().toLowerCase();
  if (!normalized) return "Verifica sessione";
  return roleLabels[normalized] || normalized;
}

export { sessionRoleLabel };
