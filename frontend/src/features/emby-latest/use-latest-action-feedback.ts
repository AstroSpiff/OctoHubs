import { useCallback, useRef, useState } from "react";

type LatestActionFeedback = {
  message: string;
  scope: LatestActionScope;
  tone: "success" | "warning" | "error";
};

type LatestActionScope = "page" | "preset" | "rule";
type SequencedFeedback = LatestActionFeedback & { sequence: number };
type FeedbackByScope = Partial<Record<LatestActionScope, SequencedFeedback>>;

const initialGenerations: Record<LatestActionScope, number> = {
  page: 0,
  preset: 0,
  rule: 0,
};

function responseMessage(result: unknown, fallback: string) {
  if (
    result &&
    typeof result === "object" &&
    "message" in result &&
    typeof result.message === "string" &&
    result.message.trim()
  ) {
    return result.message;
  }
  return fallback;
}

function errorMessage(reason: unknown) {
  return reason instanceof Error ? reason.message : "Operazione non riuscita";
}

function resultTone(result: unknown): LatestActionFeedback["tone"] {
  if (!result || typeof result !== "object") return "success";
  const outcome = result as { status?: string; success?: boolean; failed?: number; errors?: unknown[] };
  if (outcome.status === "partial" || Number(outcome.failed || 0) > 0 || (outcome.errors?.length || 0) > 0) {
    return "warning";
  }
  return outcome.success === false ? "error" : "success";
}

function useLatestActionFeedback() {
  const generationRef = useRef({ ...initialGenerations });
  const completionSequenceRef = useRef(0);
  const [feedbackByScope, setFeedbackByScope] = useState<FeedbackByScope>({});

  const run = useCallback(
    async <T,>(
      action: () => Promise<T>,
      successFallback: string,
      scope: LatestActionScope = "page",
    ): Promise<T> => {
      const generation = generationRef.current[scope] + 1;
      generationRef.current[scope] = generation;
      setFeedbackByScope((current) => {
        if (!(scope in current)) return current;
        const next = { ...current };
        delete next[scope];
        return next;
      });
      try {
        const result = await action();
        if (generationRef.current[scope] === generation) {
          const sequence = completionSequenceRef.current + 1;
          completionSequenceRef.current = sequence;
          setFeedbackByScope((current) => ({
            ...current,
            [scope]: {
              message: responseMessage(result, successFallback),
              scope,
              tone: resultTone(result),
              sequence,
            },
          }));
        }
        return result;
      } catch (reason) {
        if (generationRef.current[scope] === generation) {
          const sequence = completionSequenceRef.current + 1;
          completionSequenceRef.current = sequence;
          setFeedbackByScope((current) => ({
            ...current,
            [scope]: {
              message: errorMessage(reason),
              scope,
              tone: "error",
              sequence,
            },
          }));
        }
        throw reason;
      }
    },
    [],
  );

  const errorFor = useCallback(
    (scope: LatestActionScope) =>
      feedbackByScope[scope]?.tone === "error"
        ? feedbackByScope[scope]?.message
        : undefined,
    [feedbackByScope],
  );
  const entries = Object.values(feedbackByScope).sort(
    (left, right) => right.sequence - left.sequence,
  );
  const expose = (value: SequencedFeedback | undefined): LatestActionFeedback | null =>
    value
      ? { message: value.message, scope: value.scope, tone: value.tone }
      : null;
  const feedback = expose(entries[0]);
  const notice = expose(entries.find(
    (entry) => entry.tone !== "error" || entry.scope === "page",
  ));

  return { errorFor, feedback, notice, run };
}

export { useLatestActionFeedback };
export type { LatestActionFeedback, LatestActionScope };
