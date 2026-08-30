import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { SetStateAction } from "react";

function snapshot(value: unknown): string {
  return JSON.stringify(value);
}

/**
 * Keeps a form draft stable while its query refreshes in the background.
 * A newer server snapshot is applied once the local draft is no longer dirty.
 */
function useSynchronizedDraft<TSource, TDraft>(
  source: TSource | undefined,
  toDraft: (source: TSource) => TDraft,
) {
  const sourceSignature = useMemo(
    () => (source === undefined ? "" : snapshot(source)),
    [source],
  );
  const observedSourceSignature = useRef(sourceSignature || null);
  const initialDraft = source === undefined ? null : toDraft(source);
  const [draft, setDraftState] = useState<TDraft | null>(initialDraft);
  const draftRef = useRef<TDraft | null>(initialDraft);
  const [baseline, setBaseline] = useState<string | null>(() =>
    source === undefined ? null : snapshot(toDraft(source)),
  );
  const [pendingSource, setPendingSource] = useState<TSource | undefined>();
  const dirty =
    draft !== null && baseline !== null && snapshot(draft) !== baseline;

  const applySource = useCallback(
    (nextSource: TSource) => {
      const nextDraft = toDraft(nextSource);
      draftRef.current = nextDraft;
      setDraftState(nextDraft);
      setBaseline(snapshot(nextDraft));
      setPendingSource(undefined);
    },
    [toDraft],
  );

  useEffect(() => {
    if (
      source === undefined ||
      !sourceSignature ||
      sourceSignature === observedSourceSignature.current
    ) {
      return;
    }
    observedSourceSignature.current = sourceSignature;
    if (dirty) {
      setPendingSource(source);
      return;
    }
    applySource(source);
  }, [applySource, dirty, source, sourceSignature]);

  useEffect(() => {
    if (!dirty && pendingSource !== undefined) applySource(pendingSource);
  }, [applySource, dirty, pendingSource]);

  const accept = useCallback(
    (nextSource: TSource, expectedDraft?: TDraft) => {
      const nextDraft = toDraft(nextSource);
      if (
        expectedDraft !== undefined &&
        snapshot(draftRef.current) !== snapshot(expectedDraft)
      ) {
        setBaseline(snapshot(nextDraft));
        setPendingSource(undefined);
        return false;
      }
      applySource(nextSource);
      return true;
    },
    [applySource, toDraft],
  );
  const discard = useCallback(() => {
    if (source !== undefined) applySource(source);
  }, [applySource, source]);
  const setDraft = useCallback((action: SetStateAction<TDraft | null>) => {
    const current = draftRef.current;
    const next =
      typeof action === "function"
        ? (action as (value: TDraft | null) => TDraft | null)(current)
        : action;
    draftRef.current = next;
    setDraftState(next);
  }, []);

  return { accept, dirty, discard, draft, setDraft };
}

export { useSynchronizedDraft };
