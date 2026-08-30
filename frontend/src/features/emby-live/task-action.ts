function embyTaskActionKey(serverId: string, taskId: string) {
  return `${serverId}:${taskId}`;
}

export { embyTaskActionKey };
