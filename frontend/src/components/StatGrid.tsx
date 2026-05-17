import { safeJsonParse, statName } from "@/lib/utils";
import type { StatBlock } from "@/types/api";

const statKeys = ["hp", "physical_attack", "physical_defense", "magic_attack", "magic_defense", "speed"] as const;

export function StatGrid({ statsJson, stats }: { statsJson?: string | null; stats?: Partial<StatBlock> | null }) {
  const parsed = stats ?? safeJsonParse<Partial<StatBlock>>(statsJson, {});
  return (
    <div className="grid grid-cols-3 gap-2">
      {statKeys.map((key) => (
        <div key={key} className="rounded-xl border bg-white p-2">
          <div className="text-xs text-muted-foreground">{statName(key)}</div>
          <div className="text-base font-semibold">{parsed[key] ?? "--"}</div>
        </div>
      ))}
    </div>
  );
}
