import { WorkspaceChoiceGroup } from "@/components/ui/workspace-choice-group";
import type {
  ProbeDataTab,
  ProbeDataTabOption,
} from "@/features/probe/probe-data-tab-options";

type ProbeDataTabsProps = {
  value: ProbeDataTab;
  tabs: ProbeDataTabOption[];
  onChange: (tab: ProbeDataTab) => Promise<boolean>;
};

function ProbeDataTabs({ value, tabs, onChange }: ProbeDataTabsProps) {
  return (
    <WorkspaceChoiceGroup
      ariaLabel="Dati Probe"
      className="probe-data-tabs"
      idPrefix="probe-data-tab"
      mode="tab"
      value={value}
      options={tabs.map((tab) => ({
        id: tab.id,
        controls: `probe-data-panel-${tab.id}`,
        content: <>
          {tab.label}
          {typeof tab.count === "number" ? <span>{tab.count}</span> : null}
        </>,
      }))}
      onChange={(next) => onChange(next as ProbeDataTab)}
    />
  );
}

export { ProbeDataTabs };
