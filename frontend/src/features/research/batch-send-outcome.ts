import type { SearchResultActionNotice } from "@/features/research/components/search-result-actions";

function batchSendNotice(response: { message?: string; sent?: number; failed?: number; total?: number }, requested: number): SearchResultActionNotice {
  const failed = response.failed || 0;
  return {
    message: response.message || `${response.sent || 0}/${response.total || requested} risultati inviati a qBittorrent${failed ? `; ${failed} non inviati` : ""}.`,
    tone: failed ? "warning" : "success",
  };
}

export { batchSendNotice };
