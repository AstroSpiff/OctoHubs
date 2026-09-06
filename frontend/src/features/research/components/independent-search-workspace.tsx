import { useState } from "react";

import { IndependentSearchForm } from "@/features/research/components/independent-search-form";
import { ManualSearchHistory } from "@/features/research/components/manual-search-history";
import { SearchResults } from "@/features/research/components/search-results";
import { WriteAction } from "@/features/session/workspace-capabilities";
import type { ManualSearchQuery } from "@/features/research/manual-search-query";
import type {
  ResearchOverview,
  SearchResult,
  StreamingSearchInput,
} from "@/features/research/types";
import {
  StreamingSearchPartialError,
  useStreamingSearch,
} from "@/features/research/use-streaming-search";

function IndependentSearchWorkspace({
  overview,
  initialSearch,
}: {
  overview: ResearchOverview;
  initialSearch?: ManualSearchQuery | null;
}) {
  const streaming = useStreamingSearch();
  const [historyResults, setHistoryResults] = useState<SearchResult[] | null>(
    null,
  );
  const [historyRefreshToken, setHistoryRefreshToken] = useState(0);
  const [resultSetId, setResultSetId] = useState(0);
  const [restoredSearch, setRestoredSearch] =
    useState<StreamingSearchInput | null>(null);
  const results = historyResults === null ? streaming.results : historyResults;

  async function runSearch(input: StreamingSearchInput) {
    setHistoryResults(null);
    setResultSetId((current) => current + 1);
    try {
      await streaming.start(input);
      setHistoryRefreshToken((current) => current + 1);
    } catch (reason) {
      if (reason instanceof StreamingSearchPartialError && reason.historySaved) {
        setHistoryRefreshToken((current) => current + 1);
      }
      throw reason;
    }
  }

  return (
    <div className="research-independent-layout">
      <WriteAction>
        <IndependentSearchForm
          overview={overview}
          initialSearch={restoredSearch || initialSearch}
          searching={streaming.running}
          onCancel={streaming.cancel}
          onSearchStart={() => setHistoryResults(null)}
          onSearch={runSearch}
        />
      </WriteAction>
      {streaming.error ? (
        <div className="inline-alert inline-alert--error" role="alert">
          {streaming.error}
        </div>
      ) : null}
      {streaming.warning ? (
        <div className="inline-alert inline-alert--warning" role="status">
          {streaming.warning}
        </div>
      ) : null}
      <SearchResults
        results={results}
        searching={streaming.running}
        progress={streaming.progress}
        qbittorrentAvailable={overview.qbittorrent_available}
        resultSetId={resultSetId}
      />
      <ManualSearchHistory
        refreshToken={historyRefreshToken}
        searching={streaming.running}
        onView={(savedResults) => {
          setHistoryResults(savedResults);
          setResultSetId((current) => current + 1);
        }}
        onEdit={(input) => {
          setHistoryResults(null);
          setRestoredSearch(input);
        }}
        onRepeat={runSearch}
      />
    </div>
  );
}

export { IndependentSearchWorkspace };
