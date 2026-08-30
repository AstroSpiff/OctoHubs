import { useQuery } from "@tanstack/react-query";

import { getResearchOverview } from "@/features/research/api";

function useResearchOverview() {
  return useQuery({
    queryKey: ["research-overview"],
    queryFn: getResearchOverview,
    staleTime: 10_000,
    refetchInterval: (query) =>
      query.state.data?.scan.running ? 2_500 : 12_000,
  });
}

export { useResearchOverview };
