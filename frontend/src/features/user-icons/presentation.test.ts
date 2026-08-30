import { describe, expect, it } from "vitest";

import { iconBindingKey, iconImageUrl, userAvatarUrl, userIconTargetId } from "@/features/user-icons/presentation";

const user = { server_id: "green", user_id: "roy", server_name: "Green", name: "Roy", image_url: "/emby/roy.jpg", is_disabled: false, is_user_disabled: false, is_remote_disabled: false, enable_remote_access: true, is_admin: false, is_leader: false };

describe("user icon presentation", () => {
  it("uses the storage route and a revision for icon images", () => {
    expect(iconImageUrl("/api/emby/icons/image/p/s", 4)).toBe("/api/v1/emby/icons/image/p/s?v=4");
  });

  it("uses the exact target keys required by the icon API", () => {
    expect(iconBindingKey("group", "group-1")).toBe("group:group-1");
    expect(userIconTargetId(user)).toBe("green:roy");
  });

  it("uses the group profile image from the leader server before the Emby avatar", () => {
    const group = {
      id: "family",
      name: "Famiglia",
      is_linked: true,
      users: [user, { ...user, server_id: "violet", user_id: "luca", name: "Luca", is_leader: true }],
    };
    const config = {
      profiles: [],
      bindings: { "group:family": "family-icon" },
      matrix: { "family-icon": { violet: "/api/emby/icons/image/family-icon/violet" } },
    };

    expect(userAvatarUrl(group, user, config, 12)).toBe("/api/v1/emby/icons/image/family-icon/violet?v=12");
  });

  it("uses a direct binding for standalone users and otherwise preserves the Emby avatar", () => {
    const group = { id: "single-roy", name: "Roy", is_linked: false, users: [user] };

    expect(userAvatarUrl(group, user, { profiles: [], bindings: { "user:green:roy": "roy-icon" }, matrix: { "roy-icon": { green: "/api/emby/icons/image/roy-icon/green" } } }, 7)).toBe("/api/v1/emby/icons/image/roy-icon/green?v=7");
    expect(userAvatarUrl(group, user, { profiles: [], bindings: {}, matrix: {} }, 7)).toBe("/emby/roy.jpg");
  });
});
