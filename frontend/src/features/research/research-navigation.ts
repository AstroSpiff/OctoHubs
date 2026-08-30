const researchTabs = ["independent", "summary", "rules", "requests"] as const;

type ResearchTab = typeof researchTabs[number];

function researchTabFromRoute(value: string | undefined): ResearchTab {
  const candidate = value || "";
  return isResearchTab(candidate) ? candidate : "independent";
}

function researchTabFromHash(hash: string): ResearchTab {
  const value = hash.replace(/^#/, "").split("?", 1)[0].trim();
  if (value === "independent-search") return "independent";
  if (value === "scan") return "summary";
  return researchTabFromRoute(value);
}

function researchPath(tab: ResearchTab) {
  return `/research/${tab}`;
}

function researchTabAtOffset(current: ResearchTab, offset: number, order: readonly ResearchTab[] = researchTabs): ResearchTab {
  const index = order.indexOf(current);
  return order[(index + offset + order.length) % order.length];
}

function isResearchTab(value: string): value is ResearchTab {
  return (researchTabs as readonly string[]).includes(value);
}

export { researchPath, researchTabAtOffset, researchTabFromHash, researchTabFromRoute, researchTabs };
export type { ResearchTab };
