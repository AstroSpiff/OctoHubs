import {
  type MouseEvent as ReactMouseEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { resultLink } from "@/features/research/api";
import { SearchResultBucket } from "@/features/research/components/search-result-bucket";
import type { SearchResultActionNotice } from "@/features/research/components/search-result-actions";
import { SearchResultBatchActions } from "@/features/research/components/search-result-batch-actions";
import { EmbyResultLookupDialog } from "@/features/research/components/emby-result-lookup-dialog";
import type { LookupTarget } from "@/features/research/components/emby-result-lookup-dialog";
import {
  SearchResultTermMenu,
} from "@/features/research/components/search-result-term-menu";
import type {
  AddTermAction,
  SearchResultTermMenuPosition,
} from "@/features/research/components/search-result-term-menu";
import { selectedResultTerm } from "@/features/research/search-result-term-selection";
import {
  groupIndexedResultsByResolution,
  groupSearchResultsBySeason,
  searchResultEntries,
} from "@/features/research/search-result-groups";
import {
  magnetExportLink,
  torrentDownloadLink,
} from "@/features/research/presentation";
import type { SearchResult } from "@/features/research/types";

function SearchResultTable({
  results,
  qbittorrentAvailable,
  onAddTerm,
}: {
  results: SearchResult[];
  qbittorrentAvailable: boolean;
  onAddTerm?: AddTermAction;
}) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [notice, setNotice] = useState<SearchResultActionNotice | null>(null);
  const [termMenu, setTermMenu] =
    useState<SearchResultTermMenuPosition | null>(null);
  const [embyLookup, setEmbyLookup] = useState<LookupTarget | null>(null);
  const termMenuRef = useRef<HTMLDivElement>(null);
  const termMenuSourceRef = useRef<HTMLElement | null>(null);
  const seasonGroups = useMemo(
    () => groupSearchResultsBySeason(results),
    [results],
  );
  const entries = useMemo(() => searchResultEntries(results), [results]);
  const selectedLinks = useMemo(
    () =>
      entries
        .flatMap(({ key, result }) =>
          selected.has(key) ? [resultLink(result)] : [],
        )
        .filter((link): link is string => Boolean(link)),
    [entries, selected],
  );
  const selectedTorrentLinks = useMemo(
    () =>
      entries
        .flatMap(({ key, result }) =>
          selected.has(key) ? [torrentDownloadLink(result)] : [],
        )
        .filter((link): link is string => Boolean(link)),
    [entries, selected],
  );
  const selectedMagnets = useMemo(
    () =>
      entries
        .flatMap(({ key, result }) =>
          selected.has(key) ? [magnetExportLink(result)] : [],
        )
        .filter((link): link is string => Boolean(link)),
    [entries, selected],
  );

  useEffect(() => setSelected(new Set()), [results]);
  const closeTermMenu = useCallback((restoreFocus = false) => {
    setTermMenu(null);
    if (restoreFocus) {
      window.requestAnimationFrame(() => termMenuSourceRef.current?.focus());
    }
  }, []);

  useEffect(() => {
    if (!termMenu) return undefined;

    function closeWhenClickingElsewhere(event: PointerEvent) {
      if (
        event.target instanceof Node &&
        !termMenuRef.current?.contains(event.target)
      ) {
        closeTermMenu();
      }
    }

    document.addEventListener("pointerdown", closeWhenClickingElsewhere);
    return () =>
      document.removeEventListener("pointerdown", closeWhenClickingElsewhere);
  }, [closeTermMenu, termMenu]);
  useEffect(() => {
    if (!termMenu) return undefined;

    const closeMenu = () => closeTermMenu();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeTermMenu(true);
      }
    };
    window.addEventListener("scroll", closeMenu, true);
    window.addEventListener("resize", closeMenu);
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      window.removeEventListener("scroll", closeMenu, true);
      window.removeEventListener("resize", closeMenu);
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [closeTermMenu, termMenu]);

  function toggle(key: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function toggleItems(keys: string[], shouldSelect: boolean) {
    setSelected((current) => {
      const next = new Set(current);
      keys.forEach((key) =>
        shouldSelect ? next.add(key) : next.delete(key),
      );
      return next;
    });
  }

  function openTermMenu(event: ReactMouseEvent<HTMLElement>) {
    if (!onAddTerm) return;
    const term = selectedResultTerm(event.currentTarget, event);
    if (!term) return;
    event.preventDefault();
    termMenuSourceRef.current = event.currentTarget;
    setTermMenu({
      term,
      x: Math.min(event.clientX, window.innerWidth - 240),
      y: Math.min(event.clientY, window.innerHeight - 140),
    });
  }

  return (
    <>
      {notice ? (
        <div
          className={`inline-alert inline-alert--${notice.tone} research-table-notice`}
          role="status"
        >
          {notice.message}
        </div>
      ) : null}
      <SearchResultBatchActions
        selectedCount={selected.size}
        canSend={qbittorrentAvailable}
        resultLinks={selectedLinks}
        torrentLinks={selectedTorrentLinks}
        magnets={selectedMagnets}
        onNotice={setNotice}
      />
      <div className="research-result-season-groups">
        {seasonGroups.map((seasonGroup) => (
          <section
            key={seasonGroup.key}
            className="research-result-season"
            {...(seasonGroup.key === "all"
              ? { "aria-label": "Risultati senza stagione" }
              : {
                  "aria-labelledby": `research-result-${seasonGroup.key}`,
                })}
          >
            {seasonGroup.key !== "all" ? (
              <header className="research-result-season-heading">
                <h3 id={`research-result-${seasonGroup.key}`}>
                  {seasonGroup.label}
                </h3>
                <small>{seasonGroup.items.length} risultati</small>
              </header>
            ) : null}
            <div className="research-result-buckets">
              {groupIndexedResultsByResolution(seasonGroup.items).map((bucket) => (
                <SearchResultBucket
                  key={bucket.key}
                  bucket={bucket}
                  canSend={qbittorrentAvailable}
                  selected={selected}
                  onToggle={toggle}
                  onToggleItems={toggleItems}
                  onNotice={setNotice}
                  onTitleContextMenu={onAddTerm ? openTermMenu : undefined}
                  onLookupEmby={setEmbyLookup}
                />
              ))}
            </div>
          </section>
        ))}
      </div>
      <SearchResultTermMenu
        menu={termMenu}
        menuRef={termMenuRef}
        onAddTerm={onAddTerm}
        onNotice={setNotice}
        onClose={closeTermMenu}
      />
      {embyLookup ? (
        <EmbyResultLookupDialog
          target={embyLookup}
          onClose={() => setEmbyLookup(null)}
        />
      ) : null}
    </>
  );
}

export { SearchResultTable };
