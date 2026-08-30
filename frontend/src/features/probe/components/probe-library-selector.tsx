import { FolderCheck } from "@/components/ui/icons";

import {
  libraryTypeBucket,
  libraryTypeLabel,
} from "@/features/libraries/presentation";
import { ProbeSelectionCheckbox } from "@/features/probe/components/probe-selection-checkbox";
import {
  librarySelectionAfterBucketToggle,
  librarySelectionState,
} from "@/features/probe/probe-library-selection";
import type { ProbeLibrary } from "@/features/probe/types";

function ProbeLibrarySelector({
  libraries,
  selected,
  disabled,
  onChange,
}: {
  libraries: ProbeLibrary[];
  selected: string[];
  disabled: boolean;
  onChange: (ids: string[]) => void;
}) {
  const allSelection = librarySelectionState(
    selected,
    libraries.map((library) => library.id),
  );
  function toggle(id: string) {
    onChange(
      selected.includes(id)
        ? selected.filter((value) => value !== id)
        : [...selected, id],
    );
  }

  function toggleBucket(ids: string[], checked: boolean) {
    onChange(librarySelectionAfterBucketToggle(selected, ids, checked));
  }

  return (
    <section
      className="probe-library-selector"
      aria-labelledby="probe-library-selector-title"
    >
      <header>
        <div>
          <FolderCheck size={16} aria-hidden="true" />
          <h3 id="probe-library-selector-title">Librerie selezionate</h3>
        </div>
        <label>
          <ProbeSelectionCheckbox
            checked={allSelection.checked}
            indeterminate={allSelection.indeterminate}
            disabled={disabled || !libraries.length}
            onChange={(event) =>
              onChange(
                event.target.checked
                  ? libraries.map((library) => library.id)
                  : [],
              )
            }
          />
          Tutte <small>{allSelection.selectedCount}/{allSelection.total}</small>
        </label>
      </header>
      {!libraries.length ? (
        <p>Nessuna libreria disponibile nel server selezionato.</p>
      ) : (
        <div>
          {(["movies", "tvshows", "other"] as const).map((bucket) => {
            const items = libraries.filter(
              (library) =>
                libraryTypeBucket(library.collection_type || "") === bucket,
            );
            const selection = librarySelectionState(
              selected,
              items.map((library) => library.id),
            );
            return items.length ? (
              <fieldset key={bucket} className="probe-library-selector-group">
                <legend className="sr-only">
                  Librerie {libraryTypeLabel(bucket)}
                </legend>
                <div className="probe-library-selector-group-header">
                  <span>
                    <strong>{libraryTypeLabel(bucket)}</strong>
                    <small>{selection.selectedCount}/{selection.total}</small>
                  </span>
                  <label
                    title={`Seleziona tutte le librerie ${libraryTypeLabel(bucket).toLowerCase()}`}
                  >
                    <ProbeSelectionCheckbox
                      ariaLabel={`Seleziona tutte le librerie ${libraryTypeLabel(bucket).toLowerCase()}`}
                      checked={selection.checked}
                      indeterminate={selection.indeterminate}
                      disabled={disabled}
                      onChange={(event) =>
                        toggleBucket(
                          items.map((library) => library.id),
                          event.target.checked,
                        )
                      }
                    />
                    <span className="sr-only">Tutte</span>
                  </label>
                </div>
                <div className="probe-library-selector-items">
                  {items.map((library) => (
                    <label key={library.id}>
                      <ProbeSelectionCheckbox
                        checked={selected.includes(library.id)}
                        disabled={disabled}
                        onChange={() => toggle(library.id)}
                      />
                      {library.name}
                    </label>
                  ))}
                </div>
              </fieldset>
            ) : null;
          })}
        </div>
      )}
    </section>
  );
}

export { ProbeLibrarySelector };
