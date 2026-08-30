import type { TraktDeviceStart } from "@/features/configuration/types";

type TraktDeviceAttempt = {
  device: TraktDeviceStart;
  clientId: string;
  clientSecret: string;
  expiresAt: number;
};

function createTraktDeviceAttempt(
  device: TraktDeviceStart,
  clientId: string,
  clientSecret: string,
  startedAt: number,
): TraktDeviceAttempt {
  const expiresIn = Number(device.expires_in);
  return {
    device,
    clientId,
    clientSecret,
    expiresAt:
      Number.isFinite(expiresIn) && expiresIn > 0
        ? startedAt + expiresIn * 1_000
        : 0,
  };
}

function traktDeviceAttemptExpired(
  attempt: TraktDeviceAttempt,
  now: number,
): boolean {
  return attempt.expiresAt > 0 && now >= attempt.expiresAt;
}

export {
  createTraktDeviceAttempt,
  traktDeviceAttemptExpired,
};
export type { TraktDeviceAttempt };
