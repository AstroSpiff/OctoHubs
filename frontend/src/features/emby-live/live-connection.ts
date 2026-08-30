import type { LiveConnectionState } from "@/features/emby-live/types";

type LiveConnectionInput = {
  connectedAt: number;
  lastPayloadAt: number;
  lastFallbackAt?: number;
  now: number;
  staleAfterMilliseconds: number;
  fallbackStaleAfterMilliseconds?: number;
};

export function liveConnectionFromHeartbeat({
  connectedAt,
  lastPayloadAt,
  lastFallbackAt = 0,
  now,
  staleAfterMilliseconds,
  fallbackStaleAfterMilliseconds = staleAfterMilliseconds,
}: LiveConnectionInput): LiveConnectionState {
  if (lastPayloadAt && now - lastPayloadAt <= staleAfterMilliseconds) {
    return "connected";
  }

  if (lastFallbackAt && now - lastFallbackAt <= fallbackStaleAfterMilliseconds) {
    return "fallback";
  }

  return now - connectedAt > staleAfterMilliseconds ? "reconnecting" : "loading";
}
