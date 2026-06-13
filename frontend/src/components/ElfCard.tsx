import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { AvatarImage } from "@/components/ui/avatar";
import { compactId, percentText } from "@/lib/utils";
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
  const name = elf.elf_name ?? elf.elf_id;
  return (
    <div className={active ? "rounded-xl border-2 border-primary bg-white p-2 shadow-sm" : "rounded-xl border bg-white p-2 shadow-sm"}>
      <div className="flex items-center gap-2">
        <AvatarImage src={typeof elf.avatar === "string" ? elf.avatar : null} alt={name} fallback={name} className="h-8 w-8 rounded-lg" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium">{name}</div>
          <div className="truncate text-[11px] text-muted-foreground">{compactId(elf.elf_id)}</div>
        </div>
        {active ? <Badge>上场</Badge> : null}
      </div>
      <div className="mt-2 grid grid-cols-2 gap-1 text-[11px]">
        <div className="rounded-lg bg-slate-50 px-1.5 py-1">HP {percentText(elf.current_hp_percent)}</div>
        <div className="rounded-lg bg-slate-50 px-1.5 py-1">能量 {elf.energy ?? 0}</div>
      </div>
      <div className="mt-2 flex gap-1">
        {!active && onSwitch ? <Button className="h-7 flex-1 px-2 text-xs" variant="outline" size="sm" onClick={onSwitch}>切换</Button> : null}
        {active && onReturn ? <Button className="h-7 flex-1 px-2 text-xs" variant="outline" size="sm" onClick={onReturn}>返场</Button> : null}
        {onSelectEstimate ? <Button className="h-7 flex-1 px-2 text-xs" variant="ghost" size="sm" onClick={onSelectEstimate}>估计</Button> : null}
      </div>
    </div>
  );
}
