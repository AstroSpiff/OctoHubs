import { Navigate } from "react-router-dom";

import { userIconsTarget } from "@/features/user-icons/user-icons-navigation";

function UserIconsPage() {
  return <Navigate replace to={userIconsTarget} />;
}

export { UserIconsPage };
