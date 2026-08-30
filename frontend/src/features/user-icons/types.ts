export type IconProfile = {
  id: string;
  label: string;
  is_group_profile: boolean;
};

export type UserIconConfig = {
  profiles: IconProfile[];
  matrix: Record<string, Record<string, string>>;
  bindings: Record<string, string>;
};

export type SaveIconProfileInput = {
  id?: string;
  label: string;
  isGroupProfile: boolean;
};

export type SaveIconBindingInput = {
  targetType: "group" | "user";
  targetId: string;
  profileId: string;
};
