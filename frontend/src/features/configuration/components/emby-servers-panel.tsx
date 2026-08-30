import { Plus, RefreshCw, Server } from "@/components/ui/icons";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { WorkspaceHeading } from "@/components/ui/workspace-heading";
import { EmbyServerEditor } from "@/features/configuration/components/emby-server-editor";
import { EmbyServerSummary } from "@/features/configuration/components/emby-server-summary";
import { useWorkspaceCapabilities } from "@/features/session/workspace-capabilities-context";
import type { EmbyServerInput, EmbyServerSettings } from "@/features/configuration/types";

function EmbyServersPanel({ servers, loading, creating, updatingIds, deletingIds, onCreate, onUpdate, onDelete, onRefresh, onDirtyChange }: { servers: EmbyServerSettings[]; loading: boolean; creating: boolean; updatingIds: ReadonlySet<string>; deletingIds: ReadonlySet<string>; onCreate: (input: EmbyServerInput) => Promise<void>; onUpdate: (serverId: string, input: EmbyServerInput) => Promise<void>; onDelete: (serverId: string) => void; onRefresh: () => void; onDirtyChange?: (dirty: boolean) => void }) {
  const { canMutate } = useWorkspaceCapabilities();
  const [adding, setAdding] = useState(false);
  const [editorDirty, setEditorDirty] = useState<Record<string, boolean>>({});

  const updateEditorDirty = useCallback((editorId: string, dirty: boolean) => {
    setEditorDirty((current) =>
      current[editorId] === dirty ? current : { ...current, [editorId]: dirty },
    );
  }, []);

  useEffect(() => {
    onDirtyChange?.(Object.values(editorDirty).some(Boolean));
    return () => onDirtyChange?.(false);
  }, [editorDirty, onDirtyChange]);

  async function create(input: EmbyServerInput) {
    await onCreate(input);
    setAdding(false);
  }

  return <section id="configuration-servers" className="configuration-section" aria-labelledby="configuration-servers-title" tabIndex={-1}>
    <WorkspaceHeading level="section" context="Connessioni Emby" titleId="configuration-servers-title" title="Server Emby" description="Connessioni, identità visiva e disponibilità dei server gestiti da OctoHubs." actions={<>
        <Button type="button" variant="secondary" size="compact" onClick={onRefresh} disabled={loading}>
          <RefreshCw size={16} className={loading ? "animate-spin" : ""} aria-hidden="true" />
          Aggiorna
        </Button>
        <Button type="button" requiresWriteAccess variant="primary" size="compact" onClick={() => setAdding(true)} disabled={adding}>
          <Plus size={16} aria-hidden="true" />
          Aggiungi server
        </Button>
      </>} />
    {adding ? <div className="configuration-create-server"><EmbyServerEditor saving={creating} deleting={false} onSave={create} onCancel={() => setAdding(false)} editorId="new" onDirtyChange={updateEditorDirty} /></div> : null}
    {loading && !servers.length ? <p className="loading-state">Caricamento server Emby...</p> : null}
    {servers.length ? <div className="configuration-server-grid">
      {servers.map((server) => canMutate ? <EmbyServerEditor
          key={server.id}
          server={server}
          saving={updatingIds.has(server.id)}
          deleting={deletingIds.has(server.id)}
          onSave={(input) => onUpdate(server.id, input)}
          onDelete={() => onDelete(server.id)}
          editorId={server.id}
          onDirtyChange={updateEditorDirty}
        /> : <EmbyServerSummary key={server.id} server={server} />)}
    </div> : !loading && !adding ? <div className="configuration-empty"><Server size={22} aria-hidden="true" /><p>Nessun server Emby configurato.</p></div> : null}
  </section>;
}

export { EmbyServersPanel };
