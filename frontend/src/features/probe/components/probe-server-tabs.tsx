import { WorkspaceChoiceGroup } from "@/components/ui/workspace-choice-group";
import { EmbyServerIcon } from "@/features/emby-live/components/emby-server-icon";
import type { ProbeServer } from "@/features/probe/types";

function ProbeServerTabs({
  servers,
  value,
  allowAll = false,
  onChange,
}: {
  servers: ProbeServer[];
  value: string;
  allowAll?: boolean;
  onChange: (serverId: string) => boolean | void | Promise<boolean | void>;
}) {
  const options: ProbeServer[] = [
    ...(allowAll ? [{ id: "all", name: "Tutti" }] : []),
    ...servers,
  ];

  return (
    <div className="probe-server-selector">
      <WorkspaceChoiceGroup
        ariaLabel="Server Emby"
        className="probe-server-tabs"
        idPrefix="probe-server-tab"
        value={value}
        options={options.map((server) => ({
          id: server.id,
          content: <>
            {server.id !== "all" ? (
              <EmbyServerIcon
                icon={server.icon}
                iconStyle={server.icon_style}
                color={server.icon_color}
                size={14}
              />
            ) : null}
            {server.name}
          </>,
        }))}
        onChange={onChange}
      />
      <label className="probe-server-select">
        <span>Server</span>
        <select
          aria-label="Server Emby"
          value={value}
          onChange={(event) => void onChange(event.target.value)}
        >
          {options.map((server) => (
            <option key={server.id} value={server.id}>{server.name}</option>
          ))}
        </select>
      </label>
    </div>
  );
}

export { ProbeServerTabs };
