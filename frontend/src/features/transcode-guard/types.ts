export type GuardRecord = Record<string, unknown>;

export type GuardRunResult = {
  checked: number;
  violations: number;
  warned: number;
  paused: number;
  stopped: number;
  errors: string[];
};

export type GuardStreamHistory = {
  rows: GuardRecord[];
  total: number;
  correct: number;
  violations: number;
  active: number;
};

export type GuardPlaybackEvents = {
  rows: GuardRecord[];
  total: number;
};

export type TranscodeGuardStatus = {
  ok: boolean;
  running: boolean;
  active_violations: GuardRecord[];
  recent_events: GuardRecord[];
  stream_history: GuardStreamHistory;
  playback_events: GuardPlaybackEvents;
  last_result: GuardRunResult;
};

export type GuardActionResult = {
  ok: boolean;
  started?: boolean;
  stopped?: boolean;
  result?: GuardRunResult;
};
