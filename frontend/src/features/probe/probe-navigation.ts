import type { ProbeScope } from "@/features/probe/types";

function probeScopeFromHash(hash: string): ProbeScope {
  return hash.replace(/^#/, "").split("?", 1)[0].trim() === "libraries"
    ? "libraries"
    : "recent";
}

function probeScopeFromRoute(value: string | undefined): ProbeScope {
  return value === "libraries" ? "libraries" : "recent";
}

function probePath(scope: ProbeScope) {
  return `/probe/${scope}`;
}

export { probePath, probeScopeFromHash, probeScopeFromRoute };
