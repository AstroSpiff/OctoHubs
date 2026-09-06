import { useCallback, useEffect, useRef, useState } from "react";
import { Copy, Download, Save, Trash2, Upload } from "@/components/ui/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { QueryStateBoundary } from "@/components/ui/query-state-boundary";
import { deleteSettingsPreset, duplicateSettingsPreset, getSettingsPreset, getSettingsPresets, saveSettingsPreset } from "@/features/user-settings/api";
import { isSettingsPresetRealtimeEvent } from "@/features/user-settings/user-settings-realtime";
import type { SettingsPreset, UserSettings } from "@/features/user-settings/types";
import { useApplicationEventRefresh } from "@/lib/use-application-event";

type SettingsPresetControlsProps = {
  settings: UserSettings;
  applyLibraries: boolean;
  disabled: boolean;
  onLoad: (preset: SettingsPreset) => void;
  onBeforeLoad?: () => Promise<boolean>;
};

function SettingsPresetControls({
  settings,
  applyLibraries,
  disabled,
  onLoad,
  onBeforeLoad,
}: SettingsPresetControlsProps) {
  const client = useQueryClient();
  const presets = useQuery({
    queryKey: ["user-settings-presets"],
    queryFn: getSettingsPresets,
  });
  const [selectedId, setSelectedId] = useState("");
  const [label, setLabel] = useState("");
  const [error, setError] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [loadingPreset, setLoadingPreset] = useState(false);
  const selectedIdRef = useRef(selectedId);
  selectedIdRef.current = selectedId;

  const selectPreset = useCallback((preset: SettingsPreset | null) => {
    const nextId = preset?.id || "";
    selectedIdRef.current = nextId;
    setSelectedId(nextId);
    setLabel(preset?.label || "");
    setConfirmDelete(false);
  }, []);

  const cachePreset = useCallback((preset: SettingsPreset) => {
    client.setQueryData<{ ok: boolean; presets: SettingsPreset[] }>(
      ["user-settings-presets"],
      (current) => ({
        ok: true,
        presets: [
          ...(current?.presets || []).filter((item) => item.id !== preset.id),
          preset,
        ].sort((left, right) => left.label.localeCompare(right.label)),
      }),
    );
    selectPreset(preset);
  }, [client, selectPreset]);
  const refresh = useCallback(
    () => client.invalidateQueries({ queryKey: ["user-settings-presets"] }),
    [client],
  );
  const refreshFromRealtime = useCallback(() => {
    void refresh();
  }, [refresh]);
  useApplicationEventRefresh(isSettingsPresetRealtimeEvent, refreshFromRealtime);
  const save = useMutation({
    mutationFn: saveSettingsPreset,
    onSuccess: (result) => {
      cachePreset(result.preset);
      setError("");
      void refresh();
    },
  });
  const duplicate = useMutation({
    mutationFn: duplicateSettingsPreset,
    onSuccess: (result) => {
      cachePreset(result.preset);
      setError("");
      void refresh();
    },
  });
  const remove = useMutation({
    mutationFn: deleteSettingsPreset,
    onSuccess: () => {
      selectPreset(null);
      setError("");
      void refresh();
    },
  });
  const working =
    disabled ||
    loadingPreset ||
    save.isPending ||
    duplicate.isPending ||
    remove.isPending;

  useEffect(() => {
    if (!selectedId || !presets.data) return;
    const preset = presets.data?.presets.find((item) => item.id === selectedId);
    if (preset) {
      setLabel(preset.label);
      return;
    }
    selectPreset(null);
  }, [presets.data, selectPreset, selectedId]);

  async function load() {
    if (!selectedId) return setError("Seleziona un preset.");
    if (onBeforeLoad && !(await onBeforeLoad())) return;
    const presetId = selectedId;
    setLoadingPreset(true);
    setError("");
    try {
      const result = await getSettingsPreset(presetId);
      if (presetId !== selectedIdRef.current) return;
      onLoad(result.preset);
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Impossibile caricare il preset.");
    } finally {
      setLoadingPreset(false);
    }
  }

  function saveNew() {
    const nextLabel = label.trim();
    if (!nextLabel) return setError("Inserisci il nome del preset.");
    save.mutate({ label: nextLabel, settings, applyLibraries });
  }

  function update() {
    const nextLabel = label.trim();
    if (!selectedId || !nextLabel) return setError("Seleziona un preset e inserisci un nome.");
    save.mutate({ id: selectedId, label: nextLabel, settings, applyLibraries });
  }

  function createCopy() {
    const nextLabel = label.trim();
    if (!selectedId || !nextLabel) return setError("Seleziona un preset e inserisci il nome della copia.");
    duplicate.mutate({ presetId: selectedId, label: nextLabel });
  }

  const mutationError =
    error ||
    save.error?.message ||
    duplicate.error?.message ||
    remove.error?.message;

  return (
    <section className="settings-preset-controls" aria-label="Preset impostazioni">
      <header>
        <div>
          <strong>Preset impostazioni</strong>
          <small>Salva e riusa combinazioni di campi e accessi librerie.</small>
        </div>
      </header>
      <QueryStateBoundary
        error={presets.error}
        hasData={Boolean(presets.data)}
        loadingLabel="Caricamento preset impostazioni..."
        retrying={presets.isFetching}
        onRetry={() => void presets.refetch()}
      >
      {mutationError ? (
        <p className="users-dialog-error" role="alert">
          {mutationError}
        </p>
      ) : null}
      <div className="settings-preset-select">
        <select
          aria-label="Preset salvati"
          value={selectedId}
          disabled={working || presets.isLoading}
          onChange={(event) => {
            const preset = presets.data?.presets.find(
              (item) => item.id === event.target.value,
            );
            selectPreset(preset || null);
          }}
        >
          <option value="">
            {presets.data?.presets.length
              ? "Seleziona un preset"
              : "Nessun preset salvato"}
          </option>
          {presets.data?.presets.map((preset) => (
            <option key={preset.id} value={preset.id}>
              {preset.label || preset.id}
            </option>
          ))}
        </select>
        <Button
          type="button"
          variant="secondary"
          onClick={() => void load()}
          disabled={!selectedId || working}
        >
          <Download size={15} aria-hidden="true" />
          {loadingPreset ? "Caricamento..." : "Carica"}
        </Button>
      </div>
      <div className="settings-preset-actions">
        <label>
          <span>Nome preset</span>
          <input
            value={label}
            disabled={working}
            onChange={(event) => setLabel(event.target.value)}
          />
        </label>
        <Button
          type="button"
          variant="secondary"
          onClick={saveNew}
          disabled={working || !label.trim()}
        >
          <Save size={15} aria-hidden="true" />
          Salva nuovo
        </Button>
        <Button
          type="button"
          variant="primary"
          onClick={update}
          disabled={working || !selectedId || !label.trim()}
        >
          <Upload size={15} aria-hidden="true" />
          Aggiorna
        </Button>
        <Button
          type="button"
          variant="secondary"
          onClick={createCopy}
          disabled={working || !selectedId || !label.trim()}
        >
          <Copy size={15} aria-hidden="true" />
          Duplica
        </Button>
        <Button
          type="button"
          variant="danger"
          onClick={() => setConfirmDelete(true)}
          disabled={working || !selectedId}
        >
          <Trash2 size={15} aria-hidden="true" />
          Elimina
        </Button>
      </div>
      {loadingPreset ? (
        <p className="settings-preset-status" role="status">
          Caricamento preset in corso...
        </p>
      ) : null}
      {confirmDelete ? (
        <div className="settings-preset-confirm">
          <span>Eliminare definitivamente questo preset?</span>
          <Button
            type="button"
            variant="ghost"
            onClick={() => setConfirmDelete(false)}
            disabled={working}
          >
            Annulla
          </Button>
          <Button
            type="button"
            variant="danger"
            onClick={() => remove.mutate(selectedId)}
            disabled={working}
          >
            Conferma eliminazione
          </Button>
        </div>
      ) : null}
      </QueryStateBoundary>
    </section>
  );
}

export { SettingsPresetControls };
