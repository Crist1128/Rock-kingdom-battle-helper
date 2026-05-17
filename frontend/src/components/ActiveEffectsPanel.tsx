import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { effectCategoryName, ownerScopeName, sideName } from "@/lib/utils";
import type { BattleEffectInstanceDict } from "@/types/api";

export function ActiveEffectsPanel({ battleId, effects }: { battleId: string; effects: BattleEffectInstanceDict[] }) {
  const { data: definitions = [] } = useQuery({ queryKey: ["effects", "all"], queryFn: () => api.effects.list({ limit: 500 }) });
  const defById = Object.fromEntries(definitions.map((item) => [item.effect_id, item]));

  const groups = [
    { key: "elf:self", label: "我方精灵", match: (e: BattleEffectInstanceDict) => e.owner_scope === "elf" && e.owner_side === "self" },
    { key: "elf:enemy", label: "敌方精灵", match: (e: BattleEffectInstanceDict) => e.owner_scope === "elf" && e.owner_side === "enemy" },
    { key: "side", label: "队伍侧/印记", match: (e: BattleEffectInstanceDict) => e.owner_scope === "side" },
    { key: "field", label: "天气/战场", match: (e: BattleEffectInstanceDict) => e.owner_scope === "field" },
    { key: "skill_slot", label: "技能槽", match: (e: BattleEffectInstanceDict) => e.owner_scope === "skill_slot" },
    { key: "turn", label: "回合临时", match: (e: BattleEffectInstanceDict) => e.owner_scope === "turn" },
  ];

  return (
    <div className="space-y-3">
      {groups.map((group) => {
        const items = effects.filter(group.match);
        return (
          <div key={group.key} className="rounded-2xl border bg-white p-3">
            <div className="mb-2 flex items-center justify-between">
              <div className="text-sm font-semibold">{group.label}</div>
              <Badge variant="outline">{items.length}</Badge>
            </div>
            {items.length === 0 ? <div className="text-xs text-muted-foreground">暂无状态</div> : null}
            <div className="space-y-2">
              {items.map((effect) => {
                const def = defById[effect.effect_id];
                return (
                  <div key={effect.instance_id} className="flex items-center justify-between gap-2 rounded-xl bg-slate-50 p-2 text-xs">
                    <div>
                      <div className="font-medium">{def?.effect_name ?? effect.effect_id}</div>
                      <div className="text-muted-foreground">{effectCategoryName(def?.category ?? effect.category)} · {ownerScopeName(effect.owner_scope)} · {effect.owner_side ? sideName(effect.owner_side) : "战场"} · {effect.owner_elf_id ?? effect.field_id ?? effect.owner_skill_slot_id ?? "--"}</div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge variant="secondary">层 {effect.layers ?? 1}</Badge>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => api.effects.remove(effect.instance_id, { reason: "manual_remove" }).then(() => window.location.reload())}
                      >移除</Button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
