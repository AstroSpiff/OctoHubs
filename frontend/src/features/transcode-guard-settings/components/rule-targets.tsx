import { Server } from "@/components/ui/icons";

import type { GuardRule, GuardServerOption } from "@/features/transcode-guard-settings/types";

function RuleTargets({ rule, servers, onChange }: { rule: GuardRule; servers: GuardServerOption[]; onChange: (changes: Partial<GuardRule>) => void }) {
  function toggleServer(serverId: string, checked: boolean) {
    const selected = new Set(rule.server_ids);
    if (checked) selected.add(serverId); else selected.delete(serverId);
    onChange({ server_ids: [...selected] });
  }
  return (
    <section className="rule-editor-section">
      <h5><Server size={17} aria-hidden="true" /> Server interessati</h5>
      {!servers.length ? <p className="rule-editor-empty">Nessun server Emby configurato.</p> : null}
      <div className="guard-server-options">
        {servers.map((server) => <label key={server.id} className={!server.enabled ? "is-disabled" : ""}><input type="checkbox" checked={rule.server_ids.includes(server.id)} onChange={(event) => toggleServer(server.id, event.target.checked)} /><span><strong>{server.name}</strong><small>{server.enabled ? "Disponibile" : "Server disabilitato"}</small></span></label>)}
      </div>
    </section>
  );
}

export { RuleTargets };
