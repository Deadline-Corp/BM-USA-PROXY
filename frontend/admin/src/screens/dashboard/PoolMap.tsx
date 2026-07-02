import { useMemo } from "react";
import type { PoolCitySummary } from "@/shared/api/types";
import { CITY_COORDS, cityKey } from "@/shared/lib/mapCoordinates";

interface PoolMapProps {
  cities: PoolCitySummary[];
}

type NodeState = "online" | "full" | "offline";

function stateFor(c: PoolCitySummary): NodeState {
  if (c.offline_nodes > 0 && c.online_nodes === 0) return "offline";
  if (c.full_nodes > 0 && c.full_nodes === c.online_nodes + c.full_nodes) return "full";
  return "online";
}

const STATE_COLOR: Record<NodeState, string> = {
  online: "#195079",
  full: "#D99021",
  offline: "#93A7B5",
};

/** Recreates the prototype's hand-drawn US silhouette + pulsing node map
 * faithfully (see design-spec.md §5 "Map hero"). Cities not present in
 * CITY_COORDS are skipped on the map but still counted in the caller's
 * totals row. */
export function PoolMap({ cities }: PoolMapProps) {
  const nodes = useMemo(() => {
    return cities
      .map((c) => {
        const key = cityKey(c.city, c.state);
        const coord = CITY_COORDS[key];
        if (!coord) return null;
        return { city: c, coord, state: stateFor(c) };
      })
      .filter((n): n is { city: PoolCitySummary; coord: (typeof CITY_COORDS)[string]; state: NodeState } => n !== null);
  }, [cities]);

  return (
    <svg
      className="w-full h-auto block"
      viewBox="0 0 900 460"
      role="img"
      aria-label="Map of the contiguous United States with mobile proxy pool nodes"
    >
      <path
        d="M86 150 L150 132 L250 120 L360 110 L470 104 L560 100 L640 102 L700 96 L770 92 L812 112 L828 150 L820 184 L800 206 L786 236 L770 262 L740 286 L724 318 L700 340 L660 356 L612 366 L556 372 L500 380 L470 396 L440 388 L412 372 L372 362 L320 352 L268 338 L214 318 L168 296 L132 268 L104 232 L88 196 Z"
        fill="#EDF3F8"
        stroke="#C7DAEA"
        strokeWidth={1.5}
        strokeLinejoin="round"
      />

      <g stroke="#195079" strokeOpacity={0.13} strokeWidth={1.2} fill="none">
        {nodes.slice(0, -1).map((n, i) => {
          const next = nodes[i + 1];
          if (!next) return null;
          return (
            <line
              key={`${n.city.city}-${next.city.city}`}
              x1={n.coord.x}
              y1={n.coord.y}
              x2={next.coord.x}
              y2={next.coord.y}
            />
          );
        })}
      </g>

      {nodes.map((n, i) => {
        const color = STATE_COLOR[n.state];
        const pulse = n.state === "online";
        return (
          <g key={n.city.city}>
            {pulse && (
              <circle
                cx={n.coord.x}
                cy={n.coord.y}
                r={5}
                fill={color}
                className="origin-center animate-pulse-node"
                style={{ transformBox: "fill-box", animationDelay: `${(i % 7) * 0.4}s` }}
              />
            )}
            <circle cx={n.coord.x} cy={n.coord.y} r={n.state === "online" ? 5 : 5.5} fill={color} />
            {n.state !== "online" && (
              <circle cx={n.coord.x} cy={n.coord.y} r={9} fill="none" stroke={color} strokeWidth={1} strokeOpacity={0.45} />
            )}
            <text
              x={n.coord.x}
              y={n.coord.y + n.coord.labelDy}
              textAnchor="middle"
              className="font-mono"
              style={{ fontSize: 9, fill: "#7C95A8", letterSpacing: ".02em" }}
            >
              {n.city.city.toUpperCase()}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
