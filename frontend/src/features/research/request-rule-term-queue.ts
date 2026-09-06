import {
  appendRequestRuleTerm,
  type RequestRuleTermField,
} from "@/features/research/request-search-rules";
import type { RequestSearchRule } from "@/features/research/types";

type RuleTermSave = (rule: RequestSearchRule) => Promise<void>;
type SavedRule = { rule: RequestSearchRule; sourceSignature: string };

const MAX_SAVED_RULES = 256;

function ruleSignature(rule: RequestSearchRule) {
  return JSON.stringify(rule);
}

function createRequestRuleTermQueue(save: RuleTermSave) {
  const tails = new Map<string, Promise<void>>();
  const savedRules = new Map<string, SavedRule>();

  function pruneSavedRules() {
    for (const key of savedRules.keys()) {
      if (savedRules.size <= MAX_SAVED_RULES) return;
      if (!tails.has(key)) savedRules.delete(key);
    }
  }

  function enqueue(
    requestId: string | number,
    baseline: RequestSearchRule,
    term: string,
    field: RequestRuleTermField,
  ): Promise<string> {
    const key = String(requestId);
    const previous = tails.get(key) || Promise.resolve();
    const operation = previous.catch(() => undefined).then(async () => {
      const saved = savedRules.get(key);
      const current =
        saved && saved.sourceSignature === ruleSignature(baseline)
          ? saved.rule
          : baseline;
      const updated = appendRequestRuleTerm(current, field, term);
      if (updated === current) {
        return `"${term}" è già presente nelle regole della richiesta.`;
      }
      await save(updated);
      savedRules.delete(key);
      savedRules.set(key, {
        rule: updated,
        sourceSignature: ruleSignature(baseline),
      });
      pruneSavedRules();
      return `"${term}" aggiunto alle regole della richiesta.`;
    });
    const tail = operation.then(() => undefined, () => undefined);
    tails.set(key, tail);
    void tail.finally(() => {
      if (tails.get(key) === tail) {
        tails.delete(key);
        pruneSavedRules();
      }
    });
    return operation;
  }

  return { enqueue };
}

export { createRequestRuleTermQueue };
