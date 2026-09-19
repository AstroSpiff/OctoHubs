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
import type {
  OpenTermMenuAction,
  SearchResultActionNotice,
} from "@/features/research/components/search-result-actions";
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
import { useWorkspaceCapabilities } from "@/features/session/workspace-capabilities-context";
import type { SearchResult, TorrentClientOption } from "@/features/research/types";

function SearchResultTable({
  results,
  qbittorrentAvailable,
  torrentClients = [],
  onAddTerm,
  resultSetId = "static",
}: {
  results: SearchResult[];
  qbittorrentAvailable: boolean;
  torrentClients?: TorrentClientOption[];
  onAddTerm?: AddTermAction;
  resultSetId?: string | number;
}) {
  const { canMutate } = useWorkspaceCapabilities();
  const writableAddTerm = canMutate ? onAddTerm : undefined;
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

  useEffect(() => setSelected(new Set()), [resultSetId]);
  useEffect(() => {
    const availableKeys = new Set(entries.map(({ key }) => key));
    setSelected((current) => {
      const next = new Set([...current].filter((key) => availableKeys.has(key)));
      return next.size === current.size ? current : next;
    });
  }, [entries]);
  const closeTermMenu = useCallback((restoreFocus = false) => {
    setTermMenu(null);
    termMenuSourceRef.current?.setAttribute("aria-expanded", "false");
    termMenuSourceRef.current?.classList.remove("research-term-menu-anchor");
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
    if (!writableAddTerm) return;
    const term = selectedResultTerm(event.currentTarget, event);
    if (!term) return;
    event.preventDefault();
    showTermMenu(event.currentTarget, term);
  }

  const openTermMenuFromButton: OpenTermMenuAction = (source, title) => {
    if (!writableAddTerm) return;
    const term = title.trim();
    if (!term) return;
    showTermMenu(source, term);
  };

  function showTermMenu(source: HTMLElement, term: string) {
    if (termMenuSourceRef.current !== source) {
      termMenuSourceRef.current?.setAttribute("aria-expanded", "false");
      termMenuSourceRef.current?.classList.remove("research-term-menu-anchor");
    }
    termMenuSourceRef.current = source;
    source.setAttribute("aria-expanded", "true");
    source.classList.add("research-term-menu-anchor");
    setTermMenu({ term });
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
      {canMutate ? (
        <SearchResultBatchActions
          selectedCount={selected.size}
          canSend={qbittorrentAvailable}
          torrentClients={torrentClients}
          resultLinks={selectedLinks}
          torrentLinks={selectedTorrentLinks}
          magnets={selectedMagnets}
          onNotice={setNotice}
        />
      ) : null}
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
                  selectable={canMutate}
                  canSend={qbittorrentAvailable}
                  torrentClients={torrentClients}
                  selected={selected}
                  onToggle={toggle}
                  onToggleItems={toggleItems}
                  onNotice={setNotice}
                  onTitleContextMenu={writableAddTerm ? openTermMenu : undefined}
                  onOpenTermMenu={writableAddTerm ? openTermMenuFromButton : undefined}
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
        onAddTerm={writableAddTerm}
        onNotice={setNotice}
        onClose={() => closeTermMenu(true)}
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
