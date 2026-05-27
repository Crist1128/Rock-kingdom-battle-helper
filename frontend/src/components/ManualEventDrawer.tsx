import { FormEvent, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Sheet } from "@/components/ui/sheet";
import { EffectSearchSelect, SkillSearchSelect } from "@/components/EntitySearchSelect";
import { useAppStore } from "@/store/useAppStore";
import type { BattleElfStateDict, DamageDisplayType, ObservationCreate, PanelStatsInput, Side } from "@/types/api";

export function ManualEventDrawer({ battleId, state }: { battleId?: string | null; state?: { elves: BattleElfStateDict[]; battle: { turn_number: number; self_active_elf_id?: string | null; enemy_active_elf_id?: string | null } } }) {
  const queryClient = useQueryClient();
  const { activeDrawer, drawerSide, closeDrawer } = useAppStore();
  const active = activeDrawer !== null;
  const title = activeDrawer === "damage" ? "录入伤害" : activeDrawer === "resource" ? "录入治疗 / 能量" : activeDrawer === "effect" ? "录入状态" : activeDrawer === "switch" ? "切换精灵" : "手动事件";

  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["battle-state", battleId] }),
      queryClient.invalidateQueries({ queryKey: ["timeline", battleId] }),
      queryClient.invalidateQueries({ queryKey: ["candidate-summary"] }),
      queryClient.invalidateQueries({ queryKey: ["candidate-detail"] }),
      queryClient.invalidateQueries({ queryKey: ["candidate-list"] }),
    ]);
  };

  return (
    <Sheet open={active} title={title} description="MVP 手动输入：只记录事实，不执行真实公式。" onClose={closeDrawer}>
      {battleId && state && activeDrawer === "damage" ? <DamageForm battleId={battleId} state={state} defaultSide={drawerSide} onDone={() => { invalidate(); closeDrawer(); }} /> : null}
      {battleId && state && activeDrawer === "resource" ? <ResourceForm battleId={battleId} state={state} defaultSide={drawerSide} onDone={() => { invalidate(); closeDrawer(); }} /> : null}
      {battleId && state && activeDrawer === "effect" ? <EffectForm battleId={battleId} state={state} defaultSide={drawerSide} onDone={() => { invalidate(); closeDrawer(); }} /> : null}
      {battleId && state && activeDrawer === "switch" ? <SwitchForm battleId={battleId} state={state} defaultSide={drawerSide ?? "self"} onDone={() => { invalidate(); closeDrawer(); }} /> : null}
      {!battleId || !state ? <div className="text-sm text-muted-foreground">请先选择战斗并进入工作台。</div> : null}
    </Sheet>
  );
}

function useActiveElfIds(state: { battle: { self_active_elf_id?: string | null; enemy_active_elf_id?: string | null } }, defaultSide?: Side | null) {
  const attackerSide = defaultSide ?? "self";
  const defenderSide = attackerSide === "self" ? "enemy" : "self";
  return {
    attackerSide,
    attackerElfId: attackerSide === "self" ? state.battle.self_active_elf_id : state.battle.enemy_active_elf_id,
    defenderSide,
    defenderElfId: defenderSide === "self" ? state.battle.self_active_elf_id : state.battle.enemy_active_elf_id,
  };
}

function DamageForm({ battleId, state, defaultSide, onDone }: { battleId: string; state: { elves: BattleElfStateDict[]; battle: { turn_number: number; self_active_elf_id?: string | null; enemy_active_elf_id?: string | null } }; defaultSide?: Side | null; onDone: () => void }) {
  const activeIds = useActiveElfIds(state, defaultSide);
  const [damageDisplayType, setDamageDisplayType] = useState<DamageDisplayType>("single_damage");
  const [attackerSide, setAttackerSide] = useState<Side>(activeIds.attackerSide as Side);
  const [defenderSide, setDefenderSide] = useState<Side>(activeIds.defenderSide as Side);
  const [skillId, setSkillId] = useState<string | null>(null);
  const [damageValue, setDamageValue] = useState(0);
  const [perHitDamage, setPerHitDamage] = useState(0);
  const [hitCount, setHitCount] = useState(2);
  const [hpBefore, setHpBefore] = useState<number | "">(100);
  const [hpAfter, setHpAfter] = useState<number | "">("");
  const [notes, setNotes] = useState("");
  const [syncObservation, setSyncObservation] = useState(true);
  const [resolveRules, setResolveRules] = useState(true);
  const [damageTolerance, setDamageTolerance] = useState(0);

  const attackerElfId = attackerSide === "self" ? state.battle.self_active_elf_id : state.battle.enemy_active_elf_id;
  const defenderElfId = defenderSide === "self" ? state.battle.self_active_elf_id : state.battle.enemy_active_elf_id;
  const attackerElf = state.elves.find((elf) => elf.side === attackerSide && elf.elf_id === attackerElfId);
  const defenderElf = state.elves.find((elf) => elf.side === defenderSide && elf.elf_id === defenderElfId);
  const attackerPanelStats = toPanelStats(attackerElf?.panel_stats_json);
  const defenderPanelStats = toPanelStats(defenderElf?.panel_stats_json);
  const observedTotalDamage = damageDisplayType === "combo_repeated_damage" ? perHitDamage * hitCount : damageValue;
  const observationPayload = buildDamageObservationPayload({
    syncObservation,
    resolveRules,
    battleId,
    attackerSide,
    defenderSide,
    attackerElfId,
    defenderElfId,
    attackerPanelStats,
    defenderPanelStats,
    skillId,
    observedTotalDamage,
    damageTolerance,
    hitCount: damageDisplayType === "combo_repeated_damage" ? hitCount : 1,
  });

  const mutation = useMutation({ mutationFn: async () => {
    const damageEvent = await api.battles.createDamageEvent(battleId, {
      turn_number: state.battle.turn_number,
      attacker_side: attackerSide,
      attacker_elf_id: attackerElfId,
      defender_side: defenderSide,
      defender_elf_id: defenderElfId,
      skill_id: skillId,
      skill_confirmed: Boolean(skillId),
      damage_display_type: damageDisplayType,
      damage_value: damageDisplayType === "single_damage" ? damageValue : undefined,
      final_total_damage_value: damageDisplayType === "visual_total_damage" ? damageValue : undefined,
      per_hit_damage_value: damageDisplayType === "combo_repeated_damage" ? perHitDamage : undefined,
      hit_count: damageDisplayType === "combo_repeated_damage" ? hitCount : undefined,
      hp_percent_before: hpBefore === "" ? undefined : Number(hpBefore),
      hp_percent_after: hpAfter === "" ? undefined : Number(hpAfter),
      notes,
    });
    const observationResult = observationPayload
      ? await api.observations.process(battleId, observationPayload)
      : null;
    return { damageEvent, observationResult };
  }, onSuccess: onDone });

  return (
    <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); mutation.mutate(); }}>
      <SideSelect label="攻击方" value={attackerSide} onChange={setAttackerSide} />
      <SideSelect label="防御方" value={defenderSide} onChange={setDefenderSide} />
      <SkillSearchSelect label="技能" value={skillId} onChange={(id) => setSkillId(id)} />
      <div>
        <label className="text-sm font-medium">伤害显示类型</label>
        <Select value={damageDisplayType} onChange={(e) => setDamageDisplayType(e.target.value as DamageDisplayType)}>
          <option value="single_damage">单次伤害</option>
          <option value="visual_total_damage">动画多段最终总伤害</option>
          <option value="combo_repeated_damage">连击伤害</option>
        </Select>
      </div>
      {damageDisplayType !== "combo_repeated_damage" ? <NumberField label="伤害值" value={damageValue} onChange={setDamageValue} /> : null}
      {damageDisplayType === "combo_repeated_damage" ? (
        <div className="grid grid-cols-2 gap-3"><NumberField label="单段伤害" value={perHitDamage} onChange={setPerHitDamage} /><NumberField label="连击次数" value={hitCount} onChange={setHitCount} /></div>
      ) : null}
      <div className="grid grid-cols-2 gap-3">
        <NumberMaybeField label="受击前 HP%" value={hpBefore} onChange={setHpBefore} />
        <NumberMaybeField label="受击后 HP%" value={hpAfter} onChange={setHpAfter} />
      </div>
      <div className="space-y-3 rounded-2xl border bg-slate-50 p-3 text-sm">
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={syncObservation} onChange={(e) => setSyncObservation(e.target.checked)} />
          <span>同步写入候选反推观察</span>
        </label>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={resolveRules} onChange={(e) => setResolveRules(e.target.checked)} disabled={!syncObservation} />
          <span>启用后端规则解析（技能、本系、克制、应对）</span>
        </label>
        <NumberField label="伤害容差" value={damageTolerance} onChange={setDamageTolerance} />
        {syncObservation && !observationPayload ? (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900">
            当前缺少可用于反推的敌方目标、伤害值或面板信息，本次只会记录事件。
          </div>
        ) : null}
      </div>
      {mutation.error ? <div className="rounded-xl border border-red-200 bg-red-50 p-2 text-xs text-red-700">提交失败：{String((mutation.error as Error).message)}</div> : null}
      <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="备注" />
      <SubmitButton loading={mutation.isPending} />
    </form>
  );
}

interface DamageObservationBuildInput {
  syncObservation: boolean;
  resolveRules: boolean;
  battleId: string;
  attackerSide: Side;
  defenderSide: Side;
  attackerElfId?: string | null;
  defenderElfId?: string | null;
  attackerPanelStats: PanelStatsInput | null;
  defenderPanelStats: PanelStatsInput | null;
  skillId?: string | null;
  observedTotalDamage: number;
  damageTolerance: number;
  hitCount: number;
}

function buildDamageObservationPayload(input: DamageObservationBuildInput): ObservationCreate | null {
  if (!input.syncObservation || input.observedTotalDamage <= 0) return null;

  const enemyElfId = input.attackerSide === "enemy" ? input.attackerElfId : input.defenderElfId;
  if (!enemyElfId) return null;

  const enemyIsAttacker = input.attackerSide === "enemy";
  const payload: Record<string, unknown> = {
    resolve_rules: input.resolveRules,
    enemy_role: enemyIsAttacker ? "attacker" : "defender",
    skill_id: input.skillId || undefined,
    damage_tolerance: input.damageTolerance,
    hit_count: input.hitCount,
  };

  if (enemyIsAttacker) {
    if (!input.defenderPanelStats) return null;
    payload.defender_panel_stats = input.defenderPanelStats;
    payload.defender_elf_id = input.defenderElfId || undefined;
  } else {
    if (!input.attackerPanelStats) return null;
    payload.attacker_panel_stats = input.attackerPanelStats;
    payload.attacker_elf_id = input.attackerElfId || undefined;
  }

  return {
    enemy_elf_id: enemyElfId,
    observation_type: "damage_value",
    observed_value: input.observedTotalDamage,
    payload,
  };
}

function toPanelStats(rawJson?: string | null): PanelStatsInput | null {
  if (!rawJson) return null;
  try {
    const value = JSON.parse(rawJson) as Partial<Record<keyof PanelStatsInput, unknown>>;
    const stats: PanelStatsInput = {
      hp: Number(value.hp),
      physical_attack: Number(value.physical_attack),
      physical_defense: Number(value.physical_defense),
      magic_attack: Number(value.magic_attack),
      magic_defense: Number(value.magic_defense),
      speed: Number(value.speed),
    };
    return Object.values(stats).every((item) => Number.isFinite(item)) ? stats : null;
  } catch {
    return null;
  }
}

function ResourceForm({ battleId, state, defaultSide, onDone }: { battleId: string; state: { elves: BattleElfStateDict[]; battle: { turn_number: number; self_active_elf_id?: string | null; enemy_active_elf_id?: string | null } }; defaultSide?: Side | null; onDone: () => void }) {
  const [targetSide, setTargetSide] = useState<Side>(defaultSide ?? "self");
  const [resourceType, setResourceType] = useState("energy");
  const [changeType, setChangeType] = useState("gain");
  const [valueType, setValueType] = useState("value");
  const [value, setValue] = useState(1);
  const [afterValue, setAfterValue] = useState<number | "">("");
  const targetElfId = targetSide === "self" ? state.battle.self_active_elf_id : state.battle.enemy_active_elf_id;
  const mutation = useMutation({ mutationFn: () => api.battles.createResourceEvent(battleId, {
    turn_number: state.battle.turn_number,
    resource_type: resourceType,
    change_type: changeType,
    target_side: targetSide,
    target_elf_id: targetElfId,
    value_type: valueType,
    value,
    after_value: afterValue === "" ? undefined : Number(afterValue),
  }), onSuccess: onDone });
  return (
    <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); mutation.mutate(); }}>
      <SideSelect label="目标方" value={targetSide} onChange={setTargetSide} />
      <div className="grid grid-cols-2 gap-3">
        <div><label className="text-sm font-medium">资源</label><Select value={resourceType} onChange={(e) => setResourceType(e.target.value)}><option value="energy">能量</option><option value="hp">生命</option></Select></div>
        <div><label className="text-sm font-medium">变化类型</label><Select value={changeType} onChange={(e) => setChangeType(e.target.value)}><option value="gain">获得</option><option value="consume">消耗</option><option value="heal">治疗</option><option value="damage">扣除</option><option value="manual_set">手动设定</option></Select></div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div><label className="text-sm font-medium">数值类型</label><Select value={valueType} onChange={(e) => setValueType(e.target.value)}><option value="value">数值</option><option value="percent">百分比</option></Select></div>
        <NumberField label="变化值" value={value} onChange={setValue} />
      </div>
      <NumberMaybeField label="变化后观测值（可空）" value={afterValue} onChange={setAfterValue} />
      <SubmitButton loading={mutation.isPending} />
    </form>
  );
}

function EffectForm({ battleId, state, defaultSide, onDone }: { battleId: string; state: { battle: { turn_number: number; self_active_elf_id?: string | null; enemy_active_elf_id?: string | null } }; defaultSide?: Side | null; onDone: () => void }) {
  const [effectId, setEffectId] = useState<string | null>(null);
  const [ownerScope, setOwnerScope] = useState("elf");
  const [ownerSide, setOwnerSide] = useState<Side>(defaultSide ?? "self");
  const [layers, setLayers] = useState(1);
  const [remainingTurns, setRemainingTurns] = useState<number | "">("");
  const ownerElfId = ownerSide === "self" ? state.battle.self_active_elf_id : state.battle.enemy_active_elf_id;
  const mutation = useMutation({ mutationFn: () => api.effects.apply({
    battle_id: battleId,
    effect_id: effectId!,
    owner_scope: ownerScope,
    owner_side: ownerScope === "field" ? undefined : ownerSide,
    owner_elf_id: ownerScope === "elf" ? ownerElfId : undefined,
    field_id: ownerScope === "field" ? "main" : undefined,
    turn_number: state.battle.turn_number,
    layers,
    remaining_turns: remainingTurns === "" ? undefined : Number(remainingTurns),
  }), onSuccess: onDone });
  return (
    <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (effectId) mutation.mutate(); }}>
      <EffectSearchSelect label="状态" value={effectId} onChange={(id) => setEffectId(id)} />
      <div><label className="text-sm font-medium">归属范围</label><Select value={ownerScope} onChange={(e) => setOwnerScope(e.target.value)}><option value="elf">精灵</option><option value="side">队伍侧</option><option value="field">全战场</option><option value="skill_slot">技能槽</option><option value="turn">当前回合</option></Select></div>
      {ownerScope !== "field" ? <SideSelect label="归属方" value={ownerSide} onChange={setOwnerSide} /> : null}
      <div className="grid grid-cols-2 gap-3"><NumberField label="层数" value={layers} onChange={setLayers} /><NumberMaybeField label="剩余回合" value={remainingTurns} onChange={setRemainingTurns} /></div>
      <SubmitButton loading={mutation.isPending} disabled={!effectId} />
    </form>
  );
}

function SwitchForm({ battleId, state, defaultSide, onDone }: { battleId: string; state: { elves: BattleElfStateDict[]; battle: { turn_number: number } }; defaultSide: Side; onDone: () => void }) {
  const [side, setSide] = useState<Side>(defaultSide);
  const [elfId, setElfId] = useState("");
  const candidates = useMemo(() => state.elves.filter((elf) => elf.side === side), [state.elves, side]);
  useEffect(() => { if (!elfId && candidates[0]) setElfId(candidates[0].elf_id); }, [candidates, elfId]);
  const mutation = useMutation({ mutationFn: () => api.battles.switchElf(battleId, { side, elf_id: elfId, turn_number: state.battle.turn_number }), onSuccess: onDone });
  return (
    <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); mutation.mutate(); }}>
      <SideSelect label="切换方" value={side} onChange={(v) => { setSide(v); setElfId(""); }} />
      <div><label className="text-sm font-medium">新上场精灵</label><Select value={elfId} onChange={(e) => setElfId(e.target.value)}>{candidates.map((elf) => <option key={elf.elf_id} value={elf.elf_id}>{elf.elf_name ?? elf.elf_id}</option>)}</Select></div>
      <div className="rounded-2xl border bg-amber-50 p-3 text-sm text-amber-900">切换会由后端处理 clear_on_switch 状态：可切换清除的状态失效，不可清除的状态保留。</div>
      <SubmitButton loading={mutation.isPending} disabled={!elfId} />
    </form>
  );
}

function SideSelect({ label, value, onChange }: { label: string; value: Side; onChange: (side: Side) => void }) {
  return <div><label className="text-sm font-medium">{label}</label><Select value={value} onChange={(e) => onChange(e.target.value as Side)}><option value="self">我方</option><option value="enemy">敌方</option></Select></div>;
}

function NumberField({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) {
  return <div><label className="text-sm font-medium">{label}</label><Input type="number" value={value} onChange={(e) => onChange(Number(e.target.value))} /></div>;
}
function NumberMaybeField({ label, value, onChange }: { label: string; value: number | ""; onChange: (value: number | "") => void }) {
  return <div><label className="text-sm font-medium">{label}</label><Input type="number" value={value} onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))} /></div>;
}
function SubmitButton({ loading, disabled }: { loading: boolean; disabled?: boolean }) {
  return <Button className="w-full" type="submit" disabled={loading || disabled}>{loading ? "提交中..." : "提交事件"}</Button>;
}
