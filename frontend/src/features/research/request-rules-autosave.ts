type RequestRulesAutosaveState = {
  dirty: boolean;
  saving: boolean;
  revision: number;
  lastAttemptedRevision: number;
};

function shouldScheduleRequestRulesAutosave({
  dirty,
  saving,
  revision,
  lastAttemptedRevision,
}: RequestRulesAutosaveState) {
  return dirty && !saving && revision > lastAttemptedRevision;
}

export { shouldScheduleRequestRulesAutosave };
export type { RequestRulesAutosaveState };
