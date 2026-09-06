function hasAuthoritativeGuardState(snapshot: unknown, error: unknown) {
  return snapshot != null && !error;
}

function guardActionForTarget(running: boolean): "start" | "stop" {
  return running ? "start" : "stop";
}

export { guardActionForTarget, hasAuthoritativeGuardState };
