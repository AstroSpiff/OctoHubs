import { collectionSourceFromValue } from "@/features/collections/collection-source-input";
import type { CollectionEditorState } from "@/features/collections/collection-editor-state";
import type { CollectionOptions } from "@/features/collections/types";

type CollectionEditorCoreFieldsProps = {
  form: CollectionEditorState;
  options?: CollectionOptions;
  disabled: boolean;
  onUpdate: (changes: Partial<CollectionEditorState>) => void;
};

function CollectionEditorCoreFields({
  form,
  options,
  disabled,
  onUpdate,
}: CollectionEditorCoreFieldsProps) {
  const source = options?.source_types.find(
    (item) => item.value === form.source_type,
  );

  function toggleServer(serverId: string) {
    onUpdate({
      server_ids: form.server_ids.includes(serverId)
        ? form.server_ids.filter((id) => id !== serverId)
        : [...form.server_ids, serverId],
    });
  }

  return (
    <>
      <div className="collection-editor-fields">
        <label>
          <span>Nome</span>
          <input
            autoFocus
            value={form.name}
            disabled={disabled}
            onChange={(event) => onUpdate({ name: event.target.value })}
          />
        </label>
        <label>
          <span>Nome ordinamento</span>
          <input
            value={form.sort_name}
            disabled={disabled}
            onChange={(event) => onUpdate({ sort_name: event.target.value })}
            placeholder="Usa il nome collezione"
          />
        </label>
        <label>
          <span>Fonte</span>
          <select
            value={form.source_type}
            disabled={disabled}
            onChange={(event) => onUpdate({ source_type: event.target.value })}
          >
            {options?.source_types.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Link o ID lista</span>
          <input
            value={form.source_value}
            disabled={disabled}
            onChange={(event) => {
              const sourceInput = collectionSourceFromValue(event.target.value);
              onUpdate(
                sourceInput
                  ? {
                      source_type: sourceInput.sourceType,
                      source_value: sourceInput.sourceValue,
                    }
                  : { source_value: event.target.value },
              );
            }}
            placeholder={source?.placeholder || "Link o ID"}
          />
          <small>{source?.help || source?.description}</small>
        </label>
        <label className="collection-editor-full">
          <span>Descrizione</span>
          <textarea
            rows={3}
            value={form.collection_description}
            disabled={disabled}
            onChange={(event) =>
              onUpdate({ collection_description: event.target.value })
            }
          />
        </label>
        <label className="collection-editor-full">
          <span>Nome collezione in Emby</span>
          <input
            value={form.collection_sort_name}
            disabled={disabled}
            onChange={(event) =>
              onUpdate({ collection_sort_name: event.target.value })
            }
            placeholder="Usa il nome ordinamento"
          />
        </label>
      </div>
      <fieldset className="collection-editor-servers">
        <legend>Server destinazione</legend>
        <div>
          {options?.servers.map((server) => (
            <label key={server.id}>
              <input
                type="checkbox"
                checked={form.server_ids.includes(server.id)}
                disabled={disabled}
                onChange={() => toggleServer(server.id)}
              />
              {server.name}
            </label>
          ))}
        </div>
      </fieldset>
    </>
  );
}

export { CollectionEditorCoreFields };
