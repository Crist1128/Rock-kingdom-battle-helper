import { safeJsonParse, statName } from "@/lib/utils";
import type { StatBlock } from "@/types/api";

const statKeys = ["hp", "physical_attack", "physical_defense", "magic_attack", "magic_defense", "speed"] as const;

export function StatGrid({
  statsJson,
  stats,
  compact = false,
}: {
  statsJson?: string | null;
  stats?: Partial<StatBlock> | null;
  compact?: boolean;
}) {
  const parsed = stats ?? safeJsonParse<Partial<StatBlock>>(statsJson, {});
  return (
    <div className={compact ? "grid grid-cols-6 gap-1" : "grid grid-cols-3 gap-2"}>
      {statKeys.map((key) => (
        <div key={key} className={compact ? "rounded-lg border bg-white px-1.5 py-1 text-center" : "rounded-xl border bg-white p-2"}>
          <div className="text-[11px] text-muted-foreground">{statName(key)}</div>
          <div className={compact ? "text-sm font-semibold" : "text-base font-semibold"}>{parsed[key] ?? "--"}</div>
        </div>
      ))}
    </div>
  );
}
