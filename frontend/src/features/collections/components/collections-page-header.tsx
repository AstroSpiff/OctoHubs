import { FolderPlus, ListPlus, RefreshCw } from "@/components/ui/icons";

import { Button } from "@/components/ui/button";
import { WorkspaceHeading } from "@/components/ui/workspace-heading";

type CollectionsPageHeaderProps = {
  optionsLoading: boolean;
  refreshing: boolean;
  syncing: boolean;
  onOpenSources: () => void;
  onRefresh: () => void;
  onCreate: () => void;
  onSyncAll: () => void;
};

function CollectionsPageHeader({ optionsLoading, refreshing, syncing, onOpenSources, onRefresh, onCreate, onSyncAll }: CollectionsPageHeaderProps) {
  return (
    <WorkspaceHeading
      className="workspace-page-header"
      context="Liste e sincronizzazione"
      title="Collezioni"
      description="Stato delle collezioni Emby, fonti collegate, server di destinazione e sincronizzazioni in corso."
      actions={<>
        <Button type="button" variant="secondary" size="compact" onClick={onOpenSources}>
          <ListPlus size={16} aria-hidden="true" />
          Fonti
        </Button>
        <Button type="button" variant="secondary" size="compact" onClick={onRefresh} disabled={refreshing}>
          <RefreshCw size={16} className={refreshing ? "animate-spin" : ""} aria-hidden="true" />
          Aggiorna
        </Button>
        <Button type="button" requiresWriteAccess variant="secondary" size="compact" className="collections-header-create-action" onClick={onCreate} disabled={optionsLoading}>
          <FolderPlus size={16} aria-hidden="true" />
          Nuova collezione
        </Button>
        <Button type="button" requiresWriteAccess variant="primary" size="compact" onClick={onSyncAll} disabled={syncing}>
          <RefreshCw size={16} className={syncing ? "animate-spin" : ""} aria-hidden="true" />
          Sincronizza attive
        </Button>
      </>}
    />
  );
}

export { CollectionsPageHeader };
