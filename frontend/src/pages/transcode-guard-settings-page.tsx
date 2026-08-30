import { WorkspacePage } from "@/components/ui/workspace-layout";
import { GuardSettingsWorkspace } from "@/features/transcode-guard-settings/components/guard-settings-workspace";

function TranscodeGuardSettingsPage() {
  return <WorkspacePage><GuardSettingsWorkspace embedded={false} /></WorkspacePage>;
}

export { TranscodeGuardSettingsPage };
