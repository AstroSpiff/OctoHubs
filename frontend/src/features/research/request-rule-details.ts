const requestRuleCompactBreakpoint = 1_100;

function requestRuleDetailsOpenForWidth(viewportWidth?: number): boolean {
  return viewportWidth === undefined || viewportWidth > requestRuleCompactBreakpoint;
}

export { requestRuleCompactBreakpoint, requestRuleDetailsOpenForWidth };
