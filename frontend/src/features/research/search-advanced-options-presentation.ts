import type { ResearchMediaType } from "@/features/research/types";

function visibleSortMediaTypes(mediaType?: ResearchMediaType): Array<"movie" | "tv"> {
  if (mediaType === "movie") return ["movie"];
  if (mediaType === "tv") return ["tv"];
  return ["movie", "tv"];
}

export { visibleSortMediaTypes };
