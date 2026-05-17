import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { AvatarImage } from "@/components/ui/avatar";
import { compactId, percentText } from "@/lib/utils";
import type { BattleElfStateDict } from "@/types/api";

export function ElfCard({
  elf,
  active,
  onSwitch,
  onSelectCandidate,
}: {
  elf: BattleElfStateDict;
  active?: boolean;
  onSwitch?: () => void;
  onSelectCandidate?: () => void;
}) {
  const name = elf.elf_name ?? elf.elf_id;
  return (
    <div className={active ? "rounded-2xl border-2 border-primary bg-white p-3 shadow-sm" : "rounded-2xl border bg-white p-3 shadow-sm"}>
      <div className="flex items-center gap-3">
        <AvatarImage src={typeof elf.avatar === "string" ? elf.avatar : null} alt={name} fallback={name} />
        <div className="min-w-0 flex-1">
          <div className="truncate font-medium">{name}</div>
          <div className="truncate text-xs text-muted-foreground">{compactId(elf.elf_id)}</div>
        </div>
        {active ? <Badge>上场</Badge> : null}
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
        <div className="rounded-xl bg-slate-50 p-2">HP：{percentText(elf.current_hp_percent)}</div>
        <div className="rounded-xl bg-slate-50 p-2">能量：{elf.energy ?? 0}</div>
      </div>
      <div className="mt-3 flex gap-2">
        {onSwitch ? <Button className="flex-1" variant="outline" size="sm" onClick={onSwitch}>切换上场</Button> : null}
        {onSelectCandidate ? <Button className="flex-1" variant="ghost" size="sm" onClick={onSelectCandidate}>候选</Button> : null}
      </div>
    </div>
  );
}
