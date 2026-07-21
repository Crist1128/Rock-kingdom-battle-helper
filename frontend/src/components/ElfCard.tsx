import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { AvatarImage } from "@/components/ui/avatar";
import { HealthBar } from "@/components/HealthBar";
import { EnergyPips } from "@/components/EnergyPips";
import { cn, compactId } from "@/lib/utils";
import type { BattleElfStateDict } from "@/types/api";

export function ElfCard({
  elf,
  active,
  onSwitch,
  onReturn,
  onSelectEstimate,
}: {
  elf: BattleElfStateDict;
  active?: boolean;
  onSwitch?: () => void;
  onReturn?: () => void;
  onSelectEstimate?: () => void;
}) {
  const runtimeFormActive =
    elf.effective_form_source === "runtime_form"
    && typeof elf.effective_elf_id === "string"
    && elf.effective_elf_id !== elf.elf_id;
  const name = runtimeFormActive
    ? elf.effective_elf_name ?? elf.effective_elf_id ?? elf.elf_name ?? elf.elf_id
    : elf.elf_name ?? elf.elf_id;
  const avatar = runtimeFormActive ? elf.effective_avatar ?? elf.avatar : elf.avatar;
  const secondaryText = runtimeFormActive
    ? `原始：${elf.elf_name ?? compactId(elf.elf_id)}`
    : compactId(elf.elf_id);
  const maxHp = maxHpFromBattleElf(elf);
  const isSelf = elf.side === "self";
  return (
    <div
      className={cn(
        "rounded-xl border bg-raised/40 p-2 transition-shadow",
        active && isSelf && "border-self/60 shadow-[0_0_16px_hsl(var(--self)/0.18)]",
        active && !isSelf && "border-enemy/60 shadow-[0_0_16px_hsl(var(--enemy)/0.18)]",
      )}
    >
      <div className="flex items-center gap-2">
        <AvatarImage src={typeof avatar === "string" ? avatar : null} alt={name} fallback={name} className="h-9 w-9 rounded-lg" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium">{name}</div>
          <div className="truncate text-[11px] text-muted-foreground">{secondaryText}</div>
        </div>
        {runtimeFormActive ? <Badge variant="outline">形态</Badge> : null}
        {active ? (
          <span
            className={cn(
              "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-semibold",
              isSelf ? "bg-self/15 text-self" : "bg-enemy/15 text-enemy",
            )}
          >
            <span className={cn("h-1 w-1 rounded-full", isSelf ? "bg-self" : "bg-enemy")} />
            上场
          </span>
        ) : null}
      </div>
      <div className="mt-2 grid grid-cols-2 gap-1 text-[11px]">
        <div className="col-span-2 rounded-lg bg-raised/70 px-1.5 py-1">
          <HealthBar
            compact
            currentHpValue={elf.current_hp_value}
            currentHpPercent={elf.current_hp_percent}
            maxHp={maxHp}
          />
        </div>
        <div className="col-span-2 rounded-lg bg-raised/70 px-1.5 py-1">
          <EnergyPips compact value={elf.energy ?? 0} />
        </div>
      </div>
      <div className="mt-2 flex gap-1">
        {!active && onSwitch ? <Button className="h-7 flex-1 px-2 text-xs" variant="outline" size="sm" onClick={onSwitch}>切换</Button> : null}
        {active && onReturn ? <Button className="h-7 flex-1 px-2 text-xs" variant="outline" size="sm" onClick={onReturn}>返场</Button> : null}
        {onSelectEstimate ? <Button className="h-7 flex-1 px-2 text-xs" variant="ghost" size="sm" onClick={onSelectEstimate}>估计</Button> : null}
      </div>
    </div>
  );
}

function maxHpFromBattleElf(elf: BattleElfStateDict): number | null {
  const effectiveHp = hpFromUnknownStats(elf.effective_panel_stats);
  if (effectiveHp != null) return effectiveHp;
  if (!elf.panel_stats_json) return null;
  try {
    return hpFromUnknownStats(JSON.parse(elf.panel_stats_json));
  } catch {
    return null;
  }
}

function hpFromUnknownStats(value: unknown): number | null {
  if (!value || typeof value !== "object") return null;
  const hp = (value as { hp?: unknown }).hp;
  return typeof hp === "number" && Number.isFinite(hp) ? hp : null;
}
