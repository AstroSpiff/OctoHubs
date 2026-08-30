import { RefreshCw, Save } from "@/components/ui/icons";

import { Button } from "@/components/ui/button";

function GuardSettingsSave({ dirty, saving, onSave }: { dirty: boolean; saving: boolean; onSave: () => void }) {
  return (
    <Button type="button" requiresWriteAccess variant="primary" size="compact" onClick={onSave} disabled={!dirty || saving}>
      {saving ? <RefreshCw className="animate-spin" size={16} aria-hidden="true" /> : <Save size={16} aria-hidden="true" />}
      Salva regole
    </Button>
  );
}

export { GuardSettingsSave };
