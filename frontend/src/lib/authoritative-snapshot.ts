type AuthoritativeSnapshot<T> =
  | { status: "pending" }
  | { status: "error"; error: string }
  | { status: "success"; data: T };

function errorMessage(reason: unknown, fallback: string) {
  return reason instanceof Error && reason.message ? reason.message : fallback;
}

export { errorMessage };
export type { AuthoritativeSnapshot };
