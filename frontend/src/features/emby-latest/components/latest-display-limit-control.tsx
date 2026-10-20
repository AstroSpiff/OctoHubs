import { DatabaseZap } from "@/components/ui/icons";

import { latestDisplayLimits } from "@/features/emby-latest/latest-display-preferences";

function LatestDisplayLimitControl({
  displayLimit,
  maxMovies,
  maxSeries,
  onLimitChange,
}: {
  displayLimit: number;
  maxMovies?: number;
  maxSeries?: number;
  onLimitChange: (limit: number) => void;
}) {
  const databaseLimits = `${maxMovies || 0} film · ${maxSeries || 0} serie`;

  return (
    <label className="latest-display-limit">
      Mostra
      <select
        value={displayLimit}
        onChange={(event) => onLimitChange(Number(event.target.value))}
      >
        {latestDisplayLimits.map((limit) => (
          <option key={limit} value={limit}>
            {limit}
          </option>
        ))}
      </select>
      <span
        aria-label={`Limiti database: ${databaseLimits}`}
        title={`Limiti database: ${databaseLimits}`}
      >
        <DatabaseZap size={13} aria-hidden="true" />
        {databaseLimits}
      </span>
    </label>
  );
}

export { LatestDisplayLimitControl };
