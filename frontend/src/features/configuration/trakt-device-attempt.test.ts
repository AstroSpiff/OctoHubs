import { describe, expect, it } from "vitest";

import {
  createTraktDeviceAttempt,
  traktDeviceAttemptExpired,
} from "@/features/configuration/trakt-device-attempt";

const device = {
  success: true,
  device_code: "device-code",
  user_code: "USER-CODE",
  verification_url: "https://trakt.tv/activate",
  expires_in: 600,
  interval: 5,
};

describe("Trakt device attempt", () => {
  it("captures the credentials and expiry that started the authorization", () => {
    const attempt = createTraktDeviceAttempt(
      device,
      "client-at-start",
      "secret-at-start",
      1_000,
    );

    expect(attempt.clientId).toBe("client-at-start");
    expect(attempt.clientSecret).toBe("secret-at-start");
    expect(attempt.expiresAt).toBe(601_000);
    expect(traktDeviceAttemptExpired(attempt, 600_999)).toBe(false);
    expect(traktDeviceAttemptExpired(attempt, 601_000)).toBe(true);
  });

  it("does not invent an expiry when Trakt omits it", () => {
    const attempt = createTraktDeviceAttempt(
      { ...device, expires_in: 0 },
      "client",
      "secret",
      1_000,
    );

    expect(traktDeviceAttemptExpired(attempt, Number.MAX_SAFE_INTEGER)).toBe(
      false,
    );
  });
});
