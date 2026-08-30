import { CircleAlert, CircleCheck, CircleX, Clock3 } from "@/components/ui/icons";

import { requestRefreshPresentation } from "@/features/configuration/automation-presentation";
import type { RequestRefreshStatus as RequestRefreshStatusValue } from "@/features/configuration/types";

function RequestRefreshStatus({ status }: { status?: RequestRefreshStatusValue }) {
  const presentation = requestRefreshPresentation(status);
  const Icon = presentation.severity === "ok" ? CircleCheck : presentation.severity === "error" ? CircleX : presentation.severity === "warning" ? CircleAlert : Clock3;
  return <div className={`automation-runtime-status automation-runtime-status--${presentation.severity}`} role="status">
    <Icon size={14} aria-hidden="true" />
    <div><strong>{presentation.label}</strong><span>{presentation.detail}</span>{presentation.occurredAt ? <small>{presentation.occurredAt}</small> : null}</div>
  </div>;
}

export { RequestRefreshStatus };
