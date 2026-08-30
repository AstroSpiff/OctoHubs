import type { EventBridgeServer } from "@/features/event-bridge/types";

type PluginTarget = EventBridgeServer["diagnostics"]["plugin_targets"][number];

function EventBridgeTargetList({ targets }: { targets: PluginTarget[] }) {
  if (!targets.length) return null;

  return (
    <section className="bridge-targets" aria-label="Destinazioni OctoHubs dichiarate dal plugin">
      <header>
        <strong>Destinazioni dichiarate dal plugin</strong>
        <span>{targets.length}</span>
      </header>
      <ul>
        {targets.map((target, index) => (
          <li key={`${target.name}:${target.url}:${index}`}>
            <strong>{target.name || "OctoHubs"}</strong>
            <code>{target.url || "URL non comunicato"}</code>
          </li>
        ))}
      </ul>
    </section>
  );
}

export { EventBridgeTargetList };
