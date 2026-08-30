import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { UserDetailsDialog } from "@/features/users/components/user-details-dialog";

const user = {
  server_id: "green",
  server_name: "Green",
  user_id: "u1",
  name: "Roy",
  is_disabled: false,
  is_user_disabled: false,
  is_remote_disabled: false,
  enable_remote_access: true,
  is_admin: false,
  is_leader: false,
  has_password: true,
  password_status: "mismatch",
};

describe("UserDetailsDialog", () => {
  it("keeps the legacy management shortcuts and password alignment state in the profile dialog", () => {
    const markup = renderToStaticMarkup(
      <UserDetailsDialog
        user={user}
        avatarUrl="/api/emby/icons/image/family/green?v=8"
        onClose={() => undefined}
        onRename={() => undefined}
        onPassword={() => undefined}
        onClone={() => undefined}
        onDelete={() => undefined}
      />,
    );

    expect(markup).toContain("Password non allineata. Emby: presente");
    expect(markup).toContain('src="/api/emby/icons/image/family/green?v=8"');
    expect(markup).toContain("Rinomina");
    expect(markup).toContain("Password");
    expect(markup).toContain("Clona");
    expect(markup).toContain("Elimina");
  });
});
