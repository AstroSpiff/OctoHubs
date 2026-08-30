import { StatusBadge } from "@/components/ui/badge";
import { EmbyServerIcon } from "@/features/emby-live/components/emby-server-icon";
import type { EmbyServerSettings } from "@/features/configuration/types";

function EmbyServerSummary({ server }: { server: EmbyServerSettings }) {
  return (
    <article className="configuration-server-editor configuration-server-summary">
      <div className="configuration-server-editor-heading">
        <div>
          <h3>
            <EmbyServerIcon
              icon={server.icon}
              color={server.icon_color}
              iconStyle={server.icon_style}
              size={16}
            />
            {server.name}
          </h3>
          {server.original_name && server.original_name !== server.name ? <p>{server.original_name}</p> : null}
        </div>
        <StatusBadge severity={server.enabled ? "ok" : "neutral"}>
          {server.enabled ? "Abilitato" : "Disabilitato"}
        </StatusBadge>
      </div>
      <dl className="bridge-facts">
        <div><dt>URL Emby</dt><dd>{server.url || "Non configurato"}</dd></div>
        <div><dt>API key</dt><dd>{server.api_key_configured ? "Configurata" : "Non configurata"}</dd></div>
      </dl>
      {server.notes ? <p>{server.notes}</p> : null}
    </article>
  );
}

export { EmbyServerSummary };
