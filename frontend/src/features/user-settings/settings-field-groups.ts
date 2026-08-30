import type { SettingsField } from "@/features/user-settings/types";

type SettingsFieldGroup = {
  label?: string;
  fields: SettingsField[];
};

function groupSettingsFields(fields: SettingsField[]): SettingsFieldGroup[] {
  return fields.reduce<SettingsFieldGroup[]>((groups, field) => {
    const label = field.group;
    const previous = groups.at(-1);
    if (previous && previous.label === label) {
      previous.fields.push(field);
      return groups;
    }
    groups.push({ label, fields: [field] });
    return groups;
  }, []);
}

export { groupSettingsFields };
export type { SettingsFieldGroup };
