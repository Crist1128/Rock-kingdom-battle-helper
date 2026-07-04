import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { buildEffectLayerSummary } from "@/lib/effectLayerSummary";
import { effectCategoryName, ownerScopeName, sideName } from "@/lib/utils";
import type { BattleEffectInstanceDict } from "@/types/api";

type EffectGroup = {
  key: string;
  label: string;
  match: (effect: BattleEffectInstanceDict) => boolean;
  hideWhenEmpty?: boolean;
};

export function ActiveEffectsPanel({
  battleId,
  effects,
  turnNumber,
}: {
  battleId: string;
  effects: BattleEffectInstanceDict[];
  turnNumber: number;
}) {
  const queryClient = useQueryClient();
  const [clearLayersByInstance, setClearLayersByInstance] = useState<Record<string, number>>({});
  const { data: definitions = [] } = useQuery({ queryKey: ["effects", "all"], queryFn: () => api.effects.list({ limit: 500 }) });
  const removeMutation = useMutation({
    mutationFn: (instanceId: string) => api.effects.remove(instanceId, { reason: "manual_remove" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["battle-state", battleId] });
      queryClient.invalidateQueries({ queryKey: ["timeline", battleId] });
    },
  });
  const clearLayersMutation = useMutation({
    mutationFn: (payload: { effect: BattleEffectInstanceDict; layers: number }) =>
      api.battles.createEvent(battleId, {
        turn_number: turnNumber,
        event_type: "effect_dispel",
        actor_side: payload.effect.owner_side ?? "self",
        actor_elf_id: payload.effect.owner_elf_id ?? null,
        target_side: payload.effect.owner_side ?? null,
        target_elf_id: payload.effect.owner_elf_id ?? null,
        manual_override: true,
        payload_json: JSON.stringify({
          manual_effect_operations: [
            {
              op_type: "clear_effect_layers",
              target: payload.effect.owner_side ?? "field",
              selected_effect_instance_layers: [
                { instance_id: payload.effect.instance_id, layers: payload.layers },
              ],
            },
          ],
        }),
        notes: "手动指定消除状态层数",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["battle-state", battleId] });
      queryClient.invalidateQueries({ queryKey: ["timeline", battleId] });
    },
  });
  const defById = Object.fromEntries(definitions.map((item) => [item.effect_id, item]));

  const groups: EffectGroup[] = [
    {
      key: "elf:self",
      label: "我方精灵",
      match: (e) => e.owner_scope === "elf" && e.owner_side === "self",
    },
    {
      key: "elf:enemy",
      label: "敌方精灵",
      match: (e) => e.owner_scope === "elf" && e.owner_side === "enemy",
    },
    {
      key: "side:self",
      label: "我方队伍侧/印记",
      match: (e) => e.owner_scope === "side" && e.owner_side === "self",
    },
    {
      key: "side:enemy",
      label: "敌方队伍侧/印记",
      match: (e) => e.owner_scope === "side" && e.owner_side === "enemy",
    },
    {
      key: "side:unknown",
      label: "未指定队伍侧/印记",
      match: (e) => e.owner_scope === "side" && !e.owner_side,
      hideWhenEmpty: true,
    },
    { key: "field", label: "天气/战场", match: (e) => e.owner_scope === "field" },
    {
      key: "skill_slot",
      label: "技能槽（高级）",
      match: (e) => e.owner_scope === "skill_slot",
      hideWhenEmpty: true,
    },
    {
      key: "turn",
      label: "回合临时（高级）",
      match: (e) => e.owner_scope === "turn",
      hideWhenEmpty: true,
    },
  ];

  return (
    <div className="space-y-3">
      {groups.map((group) => {
        const items = effects.filter(group.match);
        if (group.hideWhenEmpty && items.length === 0) return null;
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
                const summary = buildEffectLayerSummary(def, effect.layers);
                return (
                  <div key={effect.instance_id} className="flex items-center justify-between gap-2 rounded-xl bg-slate-50 p-2 text-xs">
                    <div className="min-w-0 flex-1">
                      <div className="font-medium">{summary.displayName ?? def?.effect_name ?? effect.effect_id}</div>
                      <div className="text-muted-foreground">{effectCategoryName(def?.category ?? effect.category)} · {ownerScopeName(effect.owner_scope)} · {effect.owner_side ? sideName(effect.owner_side) : "战场"} · {effect.owner_elf_id ?? effect.field_id ?? effect.owner_skill_slot_id ?? "--"}</div>
                      {summary.finalTexts.length > 0 ? (
                        <div className="mt-1 flex flex-wrap gap-1">
                          {summary.finalTexts.map((text) => (
                            <Badge key={text} variant="outline" className="border-emerald-200 bg-emerald-50 text-emerald-700">
                              最终 {text}
                            </Badge>
                          ))}
                        </div>
                      ) : null}
                    </div>
                    <div className="flex flex-wrap items-center justify-end gap-2">
                      <Badge variant="secondary">{summary.layerText}</Badge>
                      <Input
                        className="h-8 w-20"
                        type="number"
                        min={1}
                        max={Number(effect.layers ?? 1)}
                        value={clearLayersByInstance[effect.instance_id] ?? 1}
                        onChange={(event) =>
                          setClearLayersByInstance((current) => ({
                            ...current,
                            [effect.instance_id]: Math.max(1, Number(event.target.value) || 1),
                          }))
                        }
                      />
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={clearLayersMutation.isPending}
                        onClick={() =>
                          clearLayersMutation.mutate({
                            effect,
                            layers: Math.min(
                              clearLayersByInstance[effect.instance_id] ?? 1,
                              Number(effect.layers ?? 1),
                            ),
                          })
                        }
                      >
                        消层
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={removeMutation.isPending}
                        onClick={() => removeMutation.mutate(effect.instance_id)}
                      >移除</Button>
                    </div>
                  </div>
                );
              })}
            </div>
            {clearLayersMutation.error ? (
              <div className="mt-2 rounded-xl border border-red-200 bg-red-50 p-2 text-xs text-red-700">
                消层失败：{String((clearLayersMutation.error as Error).message)}
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
