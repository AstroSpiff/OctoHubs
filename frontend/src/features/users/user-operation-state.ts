import type {
  BulkCloneInput,
  EmbyUser,
  PasswordTarget,
} from "@/features/users/types";

type UserOperationState = {
  applySettings?: { users: EmbyUser[] };
  clone?: BulkCloneInput;
  delete?: { user: EmbyUser };
  download?: EmbyUser;
  leader?: { user: EmbyUser };
  password?: { target: PasswordTarget };
  remote?: EmbyUser;
  rename?: { user: EmbyUser };
  unlink?: EmbyUser;
};

function sameUser(first: EmbyUser, second: EmbyUser) {
  return (
    first.server_id === second.server_id && first.user_id === second.user_id
  );
}

function isUserOperationPending(
  user: EmbyUser,
  operations: UserOperationState,
) {
  const directUsers = [
    operations.remote,
    operations.download,
    operations.unlink,
    operations.rename?.user,
    operations.delete?.user,
    operations.leader?.user,
  ].filter((candidate): candidate is EmbyUser => Boolean(candidate));

  if (directUsers.some((candidate) => sameUser(user, candidate))) return true;

  const passwordTarget = operations.password?.target;
  if (
    passwordTarget?.scope === "user" &&
    passwordTarget.serverId === user.server_id &&
    passwordTarget.userId === user.user_id
  ) {
    return true;
  }

  if (operations.applySettings?.users.some((candidate) => sameUser(user, candidate))) {
    return true;
  }

  return Boolean(
    operations.clone?.sources.some((source) => sameUser(user, source.user)),
  );
}

export { isUserOperationPending };
export type { UserOperationState };
