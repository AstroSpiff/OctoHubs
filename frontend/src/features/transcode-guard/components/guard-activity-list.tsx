import { CircleAlert, Radio } from "@/components/ui/icons";
import type { ReactNode } from "react";

import { Card } from "@/components/ui/card";
import { WorkspaceCardHeading } from "@/components/ui/workspace-card-heading";
import { actionSummary, formatGuardTime, recordText } from "@/features/transcode-guard/presentation";
import type { GuardRecord } from "@/features/transcode-guard/types";

function GuardActivityList({ title, icon, records, empty, tools }: { title: string; icon: "alert" | "event"; records: GuardRecord[]; empty: string; tools?: ReactNode }) {
  const Icon = icon === "alert" ? CircleAlert : Radio;
  return (
    <Card className="guard-activity-card">
      <WorkspaceCardHeading
        actions={tools}
        count={records.length}
        leading={<Icon size={18} />}
        title={title}
      />
      {!records.length ? <p className="guard-empty-state">{empty}</p> : null}
      <div className="guard-activity-list">
        {records.map((record, index) => <GuardActivityRow key={recordText(record, "id", String(index))} record={record} />)}
      </div>
    </Card>
  );
}

function GuardActivityRow({ record }: { record: GuardRecord }) {
  const title = recordText(record, "title", recordText(record, "event_name", "Evento player"));
  const identity = [recordText(record, "server_name", ""), recordText(record, "user", ""), recordText(record, "rule_name", "")].filter(Boolean).join(" · ");
  const time = record.at || record.updated_at || record.last_seen_at;
  return (
    <article className="guard-activity-row">
      <div><strong>{title}</strong><span>{identity || actionSummary(record)}</span></div>
      <div><b>{actionSummary(record)}</b><time>{formatGuardTime(time)}</time></div>
    </article>
  );
}

export { GuardActivityList };
