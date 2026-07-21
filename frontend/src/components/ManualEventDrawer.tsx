import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Sheet } from "@/components/ui/sheet";
import { EffectSearchSelect, SkillSearchSelect } from "@/components/EntitySearchSelect";
import { useAppStore } from "@/store/useAppStore";
import { buildEffectLayerSummary } from "@/lib/effectLayerSummary";
import { buildDamageObservationPayloadV1 } from "@/lib/observationPayload";
import { sideName } from "@/lib/utils";
import type { BattleEffectInstanceDict, BattleElfStateDict, BattleEventOut, BattleStateOut, DamageDisplayType, DamageEventCreateResult, EffectDefinitionOut, ObservationCreate, PanelStatsInput, Side, SkillDefinitionOut } from "@/types/api";

interface PlannedActionPrefill {
  kind?: string;
  skillId?: string | null;
  switchElfId?: string | null;
}

type BattleFormState = Pick<BattleStateOut, "battle" | "elves"> & Partial<Pick<BattleStateOut, "active_effects" | "skill_slots">>;

export function ManualEventDrawer({
  battleId,
  state,
  onSkillEventResult,
  onDamageEventResult,
  plannedActionBySide,
}: {
  battleId?: string | null;
  state?: BattleFormState;
  onSkillEventResult?: (event: BattleEventOut) => void;
  onDamageEventResult?: (result: DamageEventCreateResult) => void;
  plannedActionBySide?: Partial<Record<Side, PlannedActionPrefill>>;
}) {
  const queryClient = useQueryClient();
  const { activeDrawer, drawerSide, closeDrawer } = useAppStore();
  const active = activeDrawer !== null;
  const title = activeDrawer === "skill" ? "使用技能" : activeDrawer === "damage" ? "录入伤害" : activeDrawer === "resource" ? "录入治疗 / 能量" : activeDrawer === "effect" ? "录入状态" : activeDrawer === "switch" ? "切换精灵" : "手动事件";

  const invalidate = async () => {
    const queries = [
      queryClient.invalidateQueries({ queryKey: ["battle-state", battleId] }),
      queryClient.invalidateQueries({ queryKey: ["timeline", battleId] }),
      queryClient.invalidateQueries({ queryKey: ["enemy-estimate"] }),
      queryClient.invalidateQueries({ queryKey: ["enemy-estimate-evidence"] }),
    ];
    await Promise.all(queries);
  };

  return (
    <Sheet open={active} title={title} description="MVP 手动输入：只记录事实，不执行真实公式。" onClose={closeDrawer}>
      {battleId && state && activeDrawer === "skill" ? (
        <SkillUseForm
          battleId={battleId}
          state={state}
          defaultSide={drawerSide}
          plannedAction={drawerSide ? plannedActionBySide?.[drawerSide] : undefined}
          onStatusDamageDone={onDamageEventResult}
          onDone={(event) => {
            onSkillEventResult?.(event);
            invalidate();
            closeDrawer();
          }}
        />
      ) : null}
      {battleId && state && activeDrawer === "damage" ? (
        <DamageForm
          battleId={battleId}
          state={state}
          defaultSide={drawerSide}
          plannedAction={drawerSide ? plannedActionBySide?.[drawerSide] : undefined}
          onDone={(result) => {
            onDamageEventResult?.(result);
            invalidate();
            closeDrawer();
          }}
        />
      ) : null}
      {battleId && state && activeDrawer === "resource" ? <ResourceForm battleId={battleId} state={state} defaultSide={drawerSide} onDone={() => { invalidate(); closeDrawer(); }} /> : null}
      {battleId && state && activeDrawer === "effect" ? <EffectForm battleId={battleId} state={state} defaultSide={drawerSide} onDone={() => { invalidate(); closeDrawer(); }} /> : null}
      {battleId && state && activeDrawer === "switch" ? <SwitchForm battleId={battleId} state={state} defaultSide={drawerSide ?? "self"} plannedAction={drawerSide ? plannedActionBySide?.[drawerSide] : undefined} onDone={() => { invalidate(); closeDrawer(); }} /> : null}
      {!battleId || !state ? <div className="text-sm text-muted-foreground">请先选择战斗并进入工作台。</div> : null}
    </Sheet>
  );
}

function SkillUseForm({
  battleId,
  state,
  defaultSide,
  plannedAction,
  onStatusDamageDone,
  onDone,
}: {
  battleId: string;
  state: BattleFormState;
  defaultSide?: Side | null;
  plannedAction?: PlannedActionPrefill;
  onStatusDamageDone?: (result: DamageEventCreateResult) => void;
  onDone: (event: BattleEventOut) => void;
}) {
  const activeIds = useActiveElfIds(state, defaultSide);
  const [actorSide, setActorSide] = useState<Side>(activeIds.attackerSide as Side);
  const [targetSide, setTargetSide] = useState<Side>(
    plannedAction?.kind === "defense_skill" ? activeIds.attackerSide as Side : activeIds.defenderSide as Side,
  );
  const [skillId, setSkillId] = useState<string | null>(plannedAction?.skillId ?? null);
  const [responseAttackSuccess, setResponseAttackSuccess] = useState<OptionalBoolInput>("");
  const [responseDefenseSuccess, setResponseDefenseSuccess] = useState<OptionalBoolInput>("");
  const [responseStatusSuccess, setResponseStatusSuccess] = useState<OptionalBoolInput>("");
  const [actorMovesBeforeTarget, setActorMovesBeforeTarget] = useState(false);
  const [actorMovesAfterTarget, setActorMovesAfterTarget] = useState(false);
  const [targetSwitchedThisTurn, setTargetSwitchedThisTurn] = useState(false);
  const [notes, setNotes] = useState("");
  const [recordStatusDamage, setRecordStatusDamage] = useState(false);
  const [statusEffectId, setStatusEffectId] = useState<string | null>(null);
  const [selectedStatusEffect, setSelectedStatusEffect] = useState<EffectDefinitionOut | null>(null);
  const [statusDamageDefenderSide, setStatusDamageDefenderSide] = useState<Side>(targetSide);
  const [statusDamageLayers, setStatusDamageLayers] = useState(1);
  const [statusDamageValue, setStatusDamageValue] = useState(0);
  const [statusHpBefore, setStatusHpBefore] = useState<number | "">(100);
  const [statusHpAfter, setStatusHpAfter] = useState<number | "">("");
  const [statusSyncObservation, setStatusSyncObservation] = useState(true);
  const [statusDamageTolerance, setStatusDamageTolerance] = useState(0);
  const [statusDamageSectionOpen, setStatusDamageSectionOpen] = useState(plannedAction?.kind === "status_skill");
  const [autoPrefilledKey, setAutoPrefilledKey] = useState<string | null>(null);
  const [skillHitCount, setSkillHitCount] = useState(1);
  const [hitCountManuallyEdited, setHitCountManuallyEdited] = useState(false);
  const [hitCountPrefilledSkillId, setHitCountPrefilledSkillId] = useState<string | null>(null);
  const actorElfId = actorSide === "self" ? state.battle.self_active_elf_id : state.battle.enemy_active_elf_id;
  const targetElfId = targetSide === "self" ? state.battle.self_active_elf_id : state.battle.enemy_active_elf_id;
  const statusDamageDefenderElfId = statusDamageDefenderSide === "self" ? state.battle.self_active_elf_id : state.battle.enemy_active_elf_id;
  const statusDamageSourceSide: Side = actorSide === statusDamageDefenderSide ? (actorSide === "self" ? "enemy" : "self") : actorSide;
  const statusDamageSourceElfId = statusDamageSourceSide === "self" ? state.battle.self_active_elf_id : state.battle.enemy_active_elf_id;
  const statusDamageDefenderElf = state.elves.find((elf) => elf.side === statusDamageDefenderSide && elf.elf_id === statusDamageDefenderElfId);
  const statusLayerSummary = buildEffectLayerSummary(selectedStatusEffect ?? undefined, statusDamageLayers);
  const conditionFlags = buildConditionFlags({
    response_attack_success: optionalBool(responseAttackSuccess),
    response_defense_success: optionalBool(responseDefenseSuccess),
    response_status_success: optionalBool(responseStatusSuccess),
    actor_moves_before_target: actorMovesBeforeTarget || undefined,
    actor_moves_after_target: actorMovesAfterTarget || undefined,
    target_switched_this_turn: targetSwitchedThisTurn || undefined,
  });
  const selectedSkillQuery = useQuery({
    queryKey: ["skill", skillId],
    queryFn: () => api.skills.get(skillId!),
    enabled: Boolean(skillId),
    retry: false,
  });
  const activeEffectIds = useMemo(
    () => Array.from(new Set((state.active_effects ?? [])
      .filter((effect) => effect.is_active !== false && Boolean(effect.effect_id))
      .map((effect) => effect.effect_id))),
    [state.active_effects],
  );
  const activeEffectDefinitionQueries = useQueries({
    queries: activeEffectIds.map((effectId) => ({
      queryKey: ["effect", effectId],
      queryFn: () => api.effects.get(effectId),
      retry: false,
      staleTime: 5 * 60 * 1000,
    })),
  });
  const activeEffectDefinitions = new Map<string, EffectDefinitionOut>();
  activeEffectDefinitionQueries.forEach((query, index) => {
    if (query.data) activeEffectDefinitions.set(activeEffectIds[index], query.data);
  });
  const inferredStatusPrefill = useMemo(
    () => buildStatusEffectPrefill(selectedSkillQuery.data, actorSide, targetSide, skillHitCount),
    [actorSide, selectedSkillQuery.data, skillHitCount, targetSide],
  );
  const comboPrefill = useMemo(
    () => buildComboDamagePrefill(selectedSkillQuery.data),
    [selectedSkillQuery.data],
  );
  const effectiveComboPrefill = buildEffectiveComboPrefill({
    basePrefill: comboPrefill,
    skill: selectedSkillQuery.data,
    activeEffects: state.active_effects ?? [],
    effectDefinitions: activeEffectDefinitions,
    skillSlots: state.skill_slots ?? [],
    actorSide,
    actorElfId,
    conditionFlags,
  });
  const selectedStatusEffectQuery = useQuery({
    queryKey: ["effect", statusEffectId],
    queryFn: () => api.effects.get(statusEffectId!),
    enabled: Boolean(statusEffectId && selectedStatusEffect?.effect_id !== statusEffectId),
    retry: false,
  });

  useEffect(() => {
    if (selectedStatusEffectQuery.data) {
      setSelectedStatusEffect(selectedStatusEffectQuery.data);
    }
  }, [selectedStatusEffectQuery.data]);

  useEffect(() => {
    if (!skillId) {
      setAutoPrefilledKey(null);
      setHitCountPrefilledSkillId(null);
      return;
    }
    if (
      hitCountPrefilledSkillId !== effectiveComboPrefill.prefillKey
      && selectedSkillQuery.data?.skill_id === skillId
      && comboPrefill.isCombo
    ) {
      if (effectiveComboPrefill.hitCount !== null && !hitCountManuallyEdited) {
        setSkillHitCount(effectiveComboPrefill.hitCount);
      }
      setHitCountPrefilledSkillId(effectiveComboPrefill.prefillKey);
    }
    if (!inferredStatusPrefill) {
      if (autoPrefilledKey) {
        setStatusEffectId(null);
        setSelectedStatusEffect(null);
        setStatusDamageLayers(1);
        setRecordStatusDamage(false);
        setAutoPrefilledKey(null);
      }
      return;
    }
    const nextPrefillKey = `${skillId}:${actorSide}:${targetSide}:${inferredStatusPrefill.effectId}:${inferredStatusPrefill.layers}`;
    if (autoPrefilledKey === nextPrefillKey) return;
    setStatusEffectId(inferredStatusPrefill.effectId);
    setSelectedStatusEffect(null);
    setStatusDamageLayers(inferredStatusPrefill.layers);
    setStatusDamageDefenderSide(inferredStatusPrefill.defenderSide);
    setStatusDamageSectionOpen(true);
    setRecordStatusDamage(false);
    setAutoPrefilledKey(nextPrefillKey);
  }, [
    actorSide,
    autoPrefilledKey,
    comboPrefill.hitCount,
    comboPrefill.isCombo,
    effectiveComboPrefill.hitCount,
    effectiveComboPrefill.prefillKey,
    hitCountManuallyEdited,
    hitCountPrefilledSkillId,
    inferredStatusPrefill,
    selectedSkillQuery.data?.skill_id,
    skillId,
    targetSide,
  ]);

  useEffect(() => {
    if (!inferredStatusPrefill) setStatusDamageDefenderSide(targetSide);
  }, [inferredStatusPrefill, targetSide]);

  useEffect(() => {
    if (statusDamageDefenderSide !== "enemy") {
      setStatusHpBefore("");
      setStatusHpAfter("");
      return;
    }
    setStatusHpBefore(normalizeHpPercent(statusDamageDefenderElf?.current_hp_percent) ?? 100);
    setStatusHpAfter("");
  }, [statusDamageDefenderSide, statusDamageDefenderElfId, statusDamageDefenderElf?.current_hp_percent]);

  const updateStatusDamageLayers = (value: number) => {
    const normalized = Math.max(1, value || 1);
    setStatusDamageLayers(
      selectedStatusEffect?.max_layers
        ? Math.min(normalized, selectedStatusEffect.max_layers)
        : normalized,
    );
  };

  const mutation = useMutation({
    mutationFn: async () => {
      const skillEvent = await api.battles.createSkillEvent(battleId, {
        turn_number: state.battle.turn_number,
        actor_side: actorSide,
        actor_elf_id: actorElfId,
        target_side: targetSide,
        target_elf_id: targetElfId,
        skill_id: skillId!,
        skill_confirmed: Boolean(skillId),
        condition_flags: Object.keys(conditionFlags).length > 0 ? conditionFlags : undefined,
        hit_count: comboPrefill.isCombo || skillHitCount > 1 ? skillHitCount : undefined,
        combo_count_source: comboPrefill.isCombo || skillHitCount > 1
          ? (hitCountManuallyEdited ? "manual_input" : effectiveComboPrefill.source)
          : undefined,
        notes,
      });
      const statusDamageResult = recordStatusDamage && statusEffectId && statusDamageValue > 0
        ? await api.battles.createDamageEvent(battleId, {
          turn_number: state.battle.turn_number,
          attacker_side: statusDamageSourceSide,
          attacker_elf_id: statusDamageSourceElfId,
          defender_side: statusDamageDefenderSide,
          defender_elf_id: statusDamageDefenderElfId,
          formula_type: "status",
          effect_id: statusEffectId,
          effect_layers: statusDamageLayers,
          damage_display_type: "single_damage",
          damage_value: statusDamageValue,
          hp_percent_before: statusDamageDefenderSide === "enemy" && statusHpBefore !== "" ? Number(statusHpBefore) : undefined,
          hp_percent_after: statusDamageDefenderSide === "enemy" && statusHpAfter !== "" ? Number(statusHpAfter) : undefined,
          sync_observation: statusSyncObservation,
          damage_tolerance: statusDamageTolerance,
          percent_tolerance: 1,
          notes: `状态技能附加结算伤害：${selectedStatusEffect?.effect_name ?? statusEffectId}`,
        })
        : undefined;
      return { skillEvent, statusDamageResult };
    },
    onSuccess: ({ skillEvent, statusDamageResult }) => {
      if (statusDamageResult) onStatusDamageDone?.(statusDamageResult);
      onDone(skillEvent);
    },
  });

  return (
    <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (skillId) mutation.mutate(); }}>
      <SideSelect label="行动方" value={actorSide} onChange={setActorSide} />
      <SideSelect label="目标方" value={targetSide} onChange={setTargetSide} />
      <SkillSearchSelect
        label="使用技能"
        value={skillId}
        onChange={(id, item) => {
          setSkillId(id);
          setHitCountManuallyEdited(false);
          setHitCountPrefilledSkillId(null);
          const prefill = buildComboDamagePrefill(item);
          if (prefill.isCombo && prefill.hitCount !== null) {
            setSkillHitCount(prefill.hitCount);
            setHitCountPrefilledSkillId(id);
          } else if (!prefill.isCombo) {
            setSkillHitCount(1);
          }
          setAutoPrefilledKey(null);
          setStatusEffectId(null);
          setSelectedStatusEffect(null);
          setStatusDamageLayers(1);
          setRecordStatusDamage(false);
        }}
        elfId={actorElfId}
        resultsMode="focus"
      />
      {comboPrefill.isCombo ? (
        <div className="rounded-2xl border bg-raised/60 p-3 text-sm">
          <NumberField
            label="连击次数"
            value={skillHitCount}
            onChange={(value) => {
              setSkillHitCount(Math.max(1, value || 1));
              setHitCountManuallyEdited(true);
            }}
          />
          <div className="mt-2 text-xs text-muted-foreground">
            当前状态技能会把这个连击次数写入事件；后端按技能规则计算状态层数时优先使用这里的手动值。
            {effectiveComboPrefill.modifierDelta !== 0
              ? ` 已按场上连击数状态自动修正 ${effectiveComboPrefill.modifierDelta > 0 ? "+" : ""}${effectiveComboPrefill.modifierDelta}。`
              : ""}
          </div>
        </div>
      ) : null}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <ResponseResultSelect label="应对攻击" value={responseAttackSuccess} onChange={setResponseAttackSuccess} />
        <ResponseResultSelect label="应对防御" value={responseDefenseSuccess} onChange={setResponseDefenseSuccess} />
        <ResponseResultSelect label="应对状态" value={responseStatusSuccess} onChange={setResponseStatusSuccess} />
      </div>
      <ConditionFlagGroup
        flags={[
          ["先于目标行动", actorMovesBeforeTarget, setActorMovesBeforeTarget],
          ["后于目标行动", actorMovesAfterTarget, setActorMovesAfterTarget],
          ["目标本回合切换", targetSwitchedThisTurn, setTargetSwitchedThisTurn],
        ]}
      />
      <div className="rounded-2xl border bg-success/10 p-3 text-sm text-success">
        技能使用会记录 `skill_use` 事件；若该技能已入库结构化操作，后端会自动执行可确定的状态、天气或资源操作。
      </div>
      <div className="rounded-2xl border bg-info/10 p-3 text-sm text-info">
        若这里记录的是防御/应对类技能，同回合下一次该精灵受击时，伤害事件可自动继承这条防御上下文。
      </div>
      <details
        className="rounded-2xl border bg-warning/10 p-3 text-sm"
        open={statusDamageSectionOpen}
        onToggle={(event) => setStatusDamageSectionOpen(event.currentTarget.open)}
      >
        <summary className="cursor-pointer font-medium text-warning">
          状态/印记结算伤害（可选）
        </summary>
        <div className="mt-3 space-y-3">
          {inferredStatusPrefill ? (
            <div className="rounded-xl border border-warning/25 bg-raised/60 p-2 text-xs text-warning">
              已从当前技能解析到：{inferredStatusPrefill.effectId} × {inferredStatusPrefill.layers} 层，
              目标为{sideName(inferredStatusPrefill.defenderSide)}。若本次还需要录入可见扣血，勾选后会默认使用这些值。
            </div>
          ) : skillId ? (
            <div className="rounded-xl border bg-raised/60 p-2 text-xs text-muted-foreground">
              当前技能没有可自动预填的状态层数；如需记录状态伤害，请手动选择状态和层数。
            </div>
          ) : null}
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={recordStatusDamage}
              onChange={(event) => setRecordStatusDamage(event.target.checked)}
            />
            <span>本次状态技能已产生可见扣血，需要一并录入</span>
          </label>
          {recordStatusDamage ? (
            <div className="space-y-3">
              <EffectSearchSelect
                label="造成伤害的状态/印记"
                value={statusEffectId}
                onChange={(id, item) => {
                  setStatusEffectId(id);
                  setSelectedStatusEffect(item);
                  setStatusDamageLayers(item.default_layers ?? 1);
                }}
                resultsMode="focus"
              />
              <SideSelect label="受伤方" value={statusDamageDefenderSide} onChange={setStatusDamageDefenderSide} />
              <div className="grid grid-cols-2 gap-3">
                <NumberField label="层数" value={statusDamageLayers} onChange={updateStatusDamageLayers} />
                <NumberField label="实际扣血数值" value={statusDamageValue} onChange={setStatusDamageValue} />
              </div>
              {statusDamageDefenderSide === "enemy" ? (
                <div className="grid grid-cols-2 gap-3">
                  <NumberMaybeField label="结算前 HP%" value={statusHpBefore} onChange={setStatusHpBefore} />
                  <NumberMaybeField label="结算后 HP%" value={statusHpAfter} onChange={setStatusHpAfter} />
                </div>
              ) : (
                <div className="rounded-xl border bg-raised/60 p-2 text-xs text-muted-foreground">
                  我方受状态伤害时会按当前精确 HP 直接扣减；敌方受伤时可额外填前后 HP% 用于反推生命资质。
                </div>
              )}
              <label className="flex items-center gap-2 text-xs">
                <input
                  type="checkbox"
                  checked={statusSyncObservation}
                  onChange={(event) => setStatusSyncObservation(event.target.checked)}
                />
                <span>写入实时面板估计观察</span>
              </label>
              <NumberField label="伤害容差" value={statusDamageTolerance} onChange={setStatusDamageTolerance} />
              <div className="text-xs text-warning">
                这里会先记录状态技能已发动，再追加一条 `formula_type=status` 的状态伤害事件；灼烧/中毒会由后端按状态规则计算克制或抵抗倍率，棘刺等真实伤害按各自状态定义处理。
              </div>
              {selectedStatusEffect ? (
                <div className="rounded-xl border bg-raised/60 p-2 text-xs text-foreground/80">
                  {statusLayerSummary.hasStructuredRule ? (
                    <div>
                      规则：{statusLayerSummary.ruleTexts.join("；")}；当前：{statusLayerSummary.layerText}，最终 {statusLayerSummary.finalTexts.join("；")}
                    </div>
                  ) : (
                    <div>当前：{statusLayerSummary.layerText}。该状态暂无结构化层数修正，只记录层数本身。</div>
                  )}
                </div>
              ) : null}
            </div>
          ) : (
            <div className="text-xs text-warning">
              如果只是施加状态、改天气或加印记，不产生本次可见扣血，保持不勾选即可。
            </div>
          )}
        </div>
      </details>
      {mutation.error ? <div className="rounded-xl border border-destructive/25 bg-destructive/10 p-2 text-xs text-destructive">提交失败：{String((mutation.error as Error).message)}</div> : null}
      <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="备注" />
      <SubmitButton loading={mutation.isPending} disabled={!skillId || (recordStatusDamage && (!statusEffectId || statusDamageValue <= 0))} />
    </form>
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

interface StatusEffectPrefill {
  effectId: string;
  layers: number;
  defenderSide: Side;
}

function buildStatusEffectPrefill(
  skill: SkillDefinitionOut | undefined,
  actorSide: Side,
  targetSide: Side,
  currentHitCount: number,
): StatusEffectPrefill | null {
  const operations = parseEffectOperations(skill?.effect_operations_json);
  for (const operation of operations) {
    const opType = asString(operation.op_type ?? operation.operation ?? operation.type);
    if (!["apply_effect", "add_layers", "dynamic_apply_effect"].includes(opType ?? "")) continue;
    const effectId = asString(operation.effect_id);
    if (!effectId) continue;
    const staticLayers = firstPositiveInteger(
      operation.layers,
      operation.add_layers,
      operation.layer_delta,
      operation.default_layers,
    );
    const layersPerHit = firstPositiveInteger(
      operation.layers_per_hit,
      operation.layers_per_combo,
      operation.layers_multiplier,
      operation.layers_per_source_layer,
    );
    const dynamicLayers = operation.layers_from === "current_hit_count"
      || operation.layers_from === "skill_hit_count"
      || operation.layers_from === "effective_hit_count"
      ? Math.max(1, currentHitCount || 1) * (layersPerHit ?? 1)
      : null;
    const layers = staticLayers ?? dynamicLayers;
    if (layers === null) continue;
    return {
      effectId,
      layers,
      defenderSide: resolveOperationTargetSide(operation.target, actorSide, targetSide),
    };
  }
  return null;
}

function parseEffectOperations(rawJson?: string | null): Record<string, unknown>[] {
  if (!rawJson) return [];
  try {
    const value = JSON.parse(rawJson) as unknown;
    if (!Array.isArray(value)) return [];
    return value.filter((item): item is Record<string, unknown> =>
      Boolean(item) && typeof item === "object" && !Array.isArray(item),
    );
  } catch {
    return [];
  }
}

function resolveOperationTargetSide(target: unknown, actorSide: Side, targetSide: Side): Side {
  if (target === "self") return "self";
  if (target === "enemy") return "enemy";
  if (target === "self_side" || target === "actor_side" || target === "source_side") {
    return actorSide;
  }
  if (target === "enemy_side" || target === "opponent_side" || target === "defender_side") {
    return actorSide === "self" ? "enemy" : "self";
  }
  if (target === "target_side" || target === "defender" || target === "target") {
    return targetSide;
  }
  return targetSide;
}

function firstPositiveInteger(...values: unknown[]): number | null {
  for (const value of values) {
    const numeric = typeof value === "number" ? value : Number(value);
    if (Number.isFinite(numeric) && numeric > 0) return Math.floor(numeric);
  }
  return null;
}

function integerValue(value: unknown): number | null {
  const numeric = typeof value === "number" ? value : Number(value);
  return Number.isFinite(numeric) ? Math.trunc(numeric) : null;
}

function numberValue(value: unknown): number | null {
  const numeric = typeof value === "number" ? value : Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

interface ComboDamagePrefill {
  isCombo: boolean;
  hitCount: number | null;
}

interface EffectiveComboPrefill {
  isCombo: boolean;
  hitCount: number | null;
  modifierDelta: number;
  modifierMultiplier: number;
  source: "skill_rule_prefill" | "auto_effect_prefill";
  prefillKey: string | null;
}

function buildComboDamagePrefill(skill: SkillDefinitionOut | null | undefined): ComboDamagePrefill {
  const hitRule = parseJsonRecord(skill?.hit_rule_json);
  const ruleHitCount = firstPositiveInteger(hitRule?.hit_count);
  const ruleDisplayType = asString(hitRule?.damage_display_type);
  const conditionalRule = parseRecordValue(hitRule?.conditional_hit_rule);
  const conditionalHitCount = firstPositiveInteger(conditionalRule?.hit_count);
  const descriptionHitCount = inferHitCountFromText(skill?.raw_description);
  const hitCount = [ruleHitCount, conditionalHitCount, descriptionHitCount].find(
    (value): value is number => typeof value === "number" && value > 1,
  ) ?? null;
  return {
    isCombo: ruleDisplayType === "combo_repeated_damage" || hitCount !== null,
    hitCount,
  };
}

function buildEffectiveComboPrefill({
  basePrefill,
  skill,
  activeEffects,
  effectDefinitions,
  skillSlots,
  actorSide,
  actorElfId,
  conditionFlags,
}: {
  basePrefill: ComboDamagePrefill;
  skill: SkillDefinitionOut | null | undefined;
  activeEffects: BattleEffectInstanceDict[];
  effectDefinitions: Map<string, EffectDefinitionOut>;
  skillSlots: NonNullable<BattleFormState["skill_slots"]>;
  actorSide: Side;
  actorElfId?: string | null;
  conditionFlags: Record<string, boolean>;
}): EffectiveComboPrefill {
  if (!basePrefill.isCombo) {
    return {
      isCombo: false,
      hitCount: null,
      modifierDelta: 0,
      modifierMultiplier: 1,
      source: "skill_rule_prefill",
      prefillKey: skill?.skill_id ? `${skill.skill_id}:not_combo` : null,
    };
  }
  const baseHitCount = Math.max(1, basePrefill.hitCount ?? 1);
  const slotId = skillSlots.find(
    (slot) =>
      slot.side === actorSide
      && slot.elf_id === actorElfId
      && slot.skill_id === skill?.skill_id,
  )?.slot_id ?? "";
  const modifier = resolveHitCountModifierFromEffects({
    activeEffects,
    effectDefinitions,
    skill,
    actorSide,
    actorElfId,
    slotId,
    conditionFlags,
  });
  const hitCount = Math.max(
    1,
    Math.trunc((baseHitCount + modifier.delta) * modifier.multiplier),
  );
  return {
    isCombo: true,
    hitCount,
    modifierDelta: modifier.delta,
    modifierMultiplier: modifier.multiplier,
    source:
      modifier.delta !== 0 || modifier.multiplier !== 1
        ? "auto_effect_prefill"
        : "skill_rule_prefill",
    prefillKey: [
      skill?.skill_id ?? "",
      actorSide,
      actorElfId ?? "",
      baseHitCount,
      modifier.signature,
      hitCount,
    ].join(":"),
  };
}

function resolveHitCountModifierFromEffects({
  activeEffects,
  effectDefinitions,
  skill,
  actorSide,
  actorElfId,
  slotId,
  conditionFlags,
}: {
  activeEffects: BattleEffectInstanceDict[];
  effectDefinitions: Map<string, EffectDefinitionOut>;
  skill: SkillDefinitionOut | null | undefined;
  actorSide: Side;
  actorElfId?: string | null;
  slotId: string;
  conditionFlags: Record<string, boolean>;
}): { delta: number; multiplier: number; signature: string } {
  let delta = 0;
  let multiplier = 1;
  const signatureParts: string[] = [];
  for (const effect of activeEffects) {
    if (!effectAppliesToActorSkill(effect, actorSide, actorElfId, slotId)) continue;
    if (typeof effect.remaining_uses === "number" && effect.remaining_uses <= 0) continue;
    const definition = effectDefinitions.get(effect.effect_id);
    const rule = parseJsonRecord(definition?.skill_modifier_json);
    if (!rule || !skillModifierRuleMatches(rule, skill, conditionFlags)) continue;
    const layers = typeof effect.layers === "number" && Number.isFinite(effect.layers) ? effect.layers : 1;
    let itemDelta = integerValue(rule.hit_count_delta) ?? 0;
    const perLayer = numberValue(rule.hit_count_delta_per_layer);
    if (perLayer !== null) itemDelta += Math.trunc(perLayer * layers);
    let itemMultiplier = numberValue(rule.hit_count_multiplier) ?? 1;
    const multiplierAddPerLayer = numberValue(rule.hit_count_multiplier_add_per_layer);
    if (multiplierAddPerLayer !== null) itemMultiplier *= 1 + multiplierAddPerLayer * layers;
    itemMultiplier = Math.max(0, itemMultiplier);
    if (itemDelta === 0 && itemMultiplier === 1) continue;
    delta += itemDelta;
    multiplier *= itemMultiplier;
    signatureParts.push(
      `${effect.instance_id}:${effect.effect_id}:${layers}:${itemDelta}:${itemMultiplier}`,
    );
  }
  return { delta, multiplier, signature: signatureParts.join("|") || "no_modifier" };
}

function effectAppliesToActorSkill(
  effect: BattleEffectInstanceDict,
  actorSide: Side,
  actorElfId: string | null | undefined,
  slotId: string,
): boolean {
  if (effect.owner_scope === "field") return true;
  if (effect.owner_scope === "side") return effect.owner_side === actorSide;
  if (effect.owner_scope === "elf") {
    return effect.owner_side === actorSide && (!actorElfId || effect.owner_elf_id === actorElfId);
  }
  if (effect.owner_scope === "skill_slot") {
    return Boolean(slotId) && effect.owner_skill_slot_id === slotId;
  }
  return false;
}

function skillModifierRuleMatches(
  rule: Record<string, unknown>,
  skill: SkillDefinitionOut | null | undefined,
  conditionFlags: Record<string, boolean>,
): boolean {
  const elementType = rule.element_type;
  if (elementType !== undefined && String(elementType) !== skill?.element_type) return false;
  const requiredConditionFlag = asString(rule.required_condition_flag);
  if (requiredConditionFlag && conditionFlags[requiredConditionFlag] !== true) return false;
  if (rule.requires_burst === true && conditionFlags.burst_triggered !== true && conditionFlags.burst_active !== true) {
    return false;
  }
  const skillCategory = rule.skill_category;
  if (skillCategory === undefined || skillCategory === null) return true;
  const actualCategory = skill?.skill_category;
  if (Array.isArray(skillCategory)) {
    return skillCategory.map(String).includes(String(actualCategory));
  }
  const expected = String(skillCategory);
  if (expected === "attack" || expected === "physical_or_magic") {
    return actualCategory === "physical" || actualCategory === "magic";
  }
  return expected === actualCategory;
}

function parseJsonRecord(rawJson?: string | null): Record<string, unknown> | null {
  if (!rawJson) return null;
  try {
    return parseRecordValue(JSON.parse(rawJson) as unknown);
  } catch {
    return null;
  }
}

function parseRecordValue(value: unknown): Record<string, unknown> | null {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function inferHitCountFromText(text?: string | null): number | null {
  if (!text) return null;
  const normalized = text.replace(/[\uFF10-\uFF19]/g, (char) =>
    String.fromCharCode(char.charCodeAt(0) - 0xfee0),
  );
  const hitUnit = "[\\u6B21\\u6BB5\\u4E0B]";
  const rangeMatch = normalized.match(
    new RegExp(`(\\d+)\\s*(?:[-~\\uFF5E\\u81F3\\u5230])\\s*(\\d+)\\s*${hitUnit}`),
  );
  if (rangeMatch) {
    const lower = Number(rangeMatch[1]);
    const upper = Number(rangeMatch[2]);
    if (Number.isFinite(lower) && Number.isFinite(upper) && Math.max(lower, upper) > 1) {
      return Math.min(lower, upper);
    }
  }
  const hitWords = [
    "\\u8FDE\\u51FB",
    "\\u8FDE\\u7EED",
    "\\u653B\\u51FB",
    "\\u9020\\u6210",
    "\\u91CD\\u590D",
    "\\u6BCF\\u56DE\\u5408",
    "\\u6BCF\\u6B21",
  ].join("|");
  const damageWords = ["\\u4F24\\u5BB3", "\\u653B\\u51FB", "\\u8FDE\\u51FB"].join("|");
  const patterns = [
    new RegExp(`(?:${hitWords})\\D{0,8}(\\d+)\\s*${hitUnit}`),
    new RegExp(`(\\d+)\\s*${hitUnit}\\D{0,8}(?:${damageWords})`),
  ];
  for (const pattern of patterns) {
    const match = normalized.match(pattern);
    const hitCount = match ? Number(match[1]) : Number.NaN;
    if (Number.isFinite(hitCount) && hitCount > 1) return Math.floor(hitCount);
  }
  return null;
}

function DamageForm({ battleId, state, defaultSide, plannedAction, onDone }: { battleId: string; state: { elves: BattleElfStateDict[]; battle: { turn_number: number; self_active_elf_id?: string | null; enemy_active_elf_id?: string | null } }; defaultSide?: Side | null; plannedAction?: PlannedActionPrefill; onDone: (result: DamageEventCreateResult) => void }) {
  const activeIds = useActiveElfIds(state, defaultSide);
  const [damageDisplayType, setDamageDisplayType] = useState<DamageDisplayType>("single_damage");
  const [attackerSide, setAttackerSide] = useState<Side>(activeIds.attackerSide as Side);
  const [defenderSide, setDefenderSide] = useState<Side>(activeIds.defenderSide as Side);
  const [skillId, setSkillId] = useState<string | null>(plannedAction?.skillId ?? null);
  const [defenseSkillId, setDefenseSkillId] = useState<string | null>(null);
  const [responseAttackSuccess, setResponseAttackSuccess] = useState<OptionalBoolInput>("");
  const [responseDefenseSuccess, setResponseDefenseSuccess] = useState<OptionalBoolInput>("");
  const [responseStatusSuccess, setResponseStatusSuccess] = useState<OptionalBoolInput>("");
  const [actorMovesBeforeTarget, setActorMovesBeforeTarget] = useState(false);
  const [actorMovesAfterTarget, setActorMovesAfterTarget] = useState(false);
  const [targetSwitchedThisTurn, setTargetSwitchedThisTurn] = useState(false);
  const [targetDefeated, setTargetDefeated] = useState(false);
  const [damageValue, setDamageValue] = useState(0);
  const [perHitDamage, setPerHitDamage] = useState(0);
  const [hitCount, setHitCount] = useState(2);
  const [hpBefore, setHpBefore] = useState<number | "">(100);
  const [hpAfter, setHpAfter] = useState<number | "">("");
  const [notes, setNotes] = useState("");
  const [syncObservation, setSyncObservation] = useState(true);
  const [resolveRules, setResolveRules] = useState(true);
  const [damageTolerance, setDamageTolerance] = useState(0);
  const [comboPrefilledSkillId, setComboPrefilledSkillId] = useState<string | null>(null);
  const [hitCountManuallyEdited, setHitCountManuallyEdited] = useState(false);

  const attackerElfId = attackerSide === "self" ? state.battle.self_active_elf_id : state.battle.enemy_active_elf_id;
  const defenderElfId = defenderSide === "self" ? state.battle.self_active_elf_id : state.battle.enemy_active_elf_id;
  const attackerElf = state.elves.find((elf) => elf.side === attackerSide && elf.elf_id === attackerElfId);
  const defenderElf = state.elves.find((elf) => elf.side === defenderSide && elf.elf_id === defenderElfId);
  const attackerPanelStats = toPanelStats(attackerElf?.panel_stats_json);
  const defenderPanelStats = toPanelStats(defenderElf?.panel_stats_json);
  const selectedDamageSkillQuery = useQuery({
    queryKey: ["skill", skillId],
    queryFn: () => api.skills.get(skillId!),
    enabled: Boolean(skillId),
    retry: false,
  });
  useEffect(() => {
    if (defenderSide === "self") {
      setHpBefore("");
      setHpAfter("");
      return;
    }
    setHpBefore(normalizeHpPercent(defenderElf?.current_hp_percent) ?? 100);
    setHpAfter("");
  }, [defenderSide, defenderElfId, defenderElf?.current_hp_percent]);
  useEffect(() => {
    if (!skillId) {
      setComboPrefilledSkillId(null);
      return;
    }
    if (comboPrefilledSkillId === skillId) return;
    if (!selectedDamageSkillQuery.data || selectedDamageSkillQuery.data.skill_id !== skillId) return;
    const prefill = buildComboDamagePrefill(selectedDamageSkillQuery.data);
    if (prefill.isCombo) {
      setDamageDisplayType("combo_repeated_damage");
      if (prefill.hitCount !== null && !hitCountManuallyEdited) setHitCount(prefill.hitCount);
    }
    setComboPrefilledSkillId(skillId);
  }, [comboPrefilledSkillId, hitCountManuallyEdited, selectedDamageSkillQuery.data, skillId]);
  const observedTotalDamage = damageDisplayType === "combo_repeated_damage" ? perHitDamage * hitCount : damageValue;
  const conditionFlags = buildConditionFlags({
    actor_moves_before_target: actorMovesBeforeTarget || undefined,
    actor_moves_after_target: actorMovesAfterTarget || undefined,
    target_switched_this_turn: targetSwitchedThisTurn || undefined,
    post_damage_defeat_condition: targetDefeated || undefined,
  });
  const observationPayloads = buildDamageObservationPayloads({
    syncObservation,
    resolveRules,
    damageDisplayType,
    battleId,
    attackerSide,
    defenderSide,
    attackerElfId,
    defenderElfId,
    attackerPanelStats,
    defenderPanelStats,
    skillId,
    defenseSkillId,
    responseAttackSuccess: optionalBool(responseAttackSuccess),
    responseDefenseSuccess: optionalBool(responseDefenseSuccess),
    responseStatusSuccess: optionalBool(responseStatusSuccess),
    observedTotalDamage,
    damageTolerance,
    hpBefore: defenderSide === "enemy" && hpBefore !== "" ? Number(hpBefore) : null,
    hpAfter: defenderSide === "enemy" && hpAfter !== "" ? Number(hpAfter) : null,
    hitCount: damageDisplayType === "combo_repeated_damage" ? hitCount : 1,
  });

  const mutation = useMutation({ mutationFn: () => (
    api.battles.createDamageEvent(battleId, {
      turn_number: state.battle.turn_number,
      attacker_side: attackerSide,
      attacker_elf_id: attackerElfId,
      defender_side: defenderSide,
      defender_elf_id: defenderElfId,
      skill_id: skillId,
      skill_confirmed: Boolean(skillId),
      defense_skill_id: defenseSkillId,
      response_attack_success: optionalBool(responseAttackSuccess),
      response_defense_success: optionalBool(responseDefenseSuccess),
      response_status_success: optionalBool(responseStatusSuccess),
      condition_flags: Object.keys(conditionFlags).length > 0 ? conditionFlags : undefined,
      damage_display_type: damageDisplayType,
      damage_value: damageDisplayType === "single_damage" ? damageValue : undefined,
      per_hit_damage_value: damageDisplayType === "combo_repeated_damage" ? perHitDamage : undefined,
      hit_count: damageDisplayType === "combo_repeated_damage" ? hitCount : undefined,
      hp_percent_before: defenderSide === "enemy" && hpBefore !== "" ? Number(hpBefore) : undefined,
      hp_percent_after: defenderSide === "enemy" && hpAfter !== "" ? Number(hpAfter) : undefined,
      sync_observation: syncObservation,
      damage_tolerance: damageTolerance,
      percent_tolerance: 1,
      notes,
    })
  ), onSuccess: onDone });

  return (
    <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); mutation.mutate(); }}>
      <SideSelect label="攻击方" value={attackerSide} onChange={setAttackerSide} />
      <SideSelect label="防御方" value={defenderSide} onChange={setDefenderSide} />
      <SkillSearchSelect
        label="技能"
        value={skillId}
        onChange={(id, item) => {
          setSkillId(id);
          setHitCountManuallyEdited(false);
          const prefill = buildComboDamagePrefill(item);
          if (prefill.isCombo) {
            setDamageDisplayType("combo_repeated_damage");
            if (prefill.hitCount !== null) setHitCount(prefill.hitCount);
          }
          setComboPrefilledSkillId(id);
        }}
        resultsMode="focus"
      />
      <details className="rounded-2xl border bg-raised/60 p-3 text-sm">
        <summary className="cursor-pointer font-medium text-foreground">
          高级覆盖：手动指定防御 / 应对上下文
        </summary>
        <div className="mt-3 space-y-3">
          <div className="rounded-xl border bg-raised/60 p-3 text-xs text-muted-foreground">
            正常回合流程下先在“结算本回合”记录防御动作，这里保持空白即可。只有补录旧事件、自动继承失败或调试后端应对字段时，才需要手动覆盖。
          </div>
          <SkillSearchSelect
            label="防御/应对技能"
            value={defenseSkillId}
            onChange={(id) => setDefenseSkillId(id)}
            elfId={defenderElfId}
            resultsMode="focus"
          />
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <ResponseResultSelect
              label="应对攻击"
              value={responseAttackSuccess}
              onChange={setResponseAttackSuccess}
            />
            <ResponseResultSelect
              label="应对防御"
              value={responseDefenseSuccess}
              onChange={setResponseDefenseSuccess}
            />
            <ResponseResultSelect
              label="应对状态"
              value={responseStatusSuccess}
              onChange={setResponseStatusSuccess}
            />
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              setDefenseSkillId(null);
              setResponseAttackSuccess("");
              setResponseDefenseSuccess("");
              setResponseStatusSuccess("");
              setActorMovesBeforeTarget(false);
              setActorMovesAfterTarget(false);
              setTargetSwitchedThisTurn(false);
              setTargetDefeated(false);
            }}
          >
            清空高级覆盖
          </Button>
        </div>
      </details>
      <ConditionFlagGroup
        flags={[
          ["先于目标行动", actorMovesBeforeTarget, setActorMovesBeforeTarget],
          ["后于目标行动", actorMovesAfterTarget, setActorMovesAfterTarget],
          ["目标本回合切换", targetSwitchedThisTurn, setTargetSwitchedThisTurn],
          ["本次击败目标", targetDefeated, setTargetDefeated],
        ]}
      />
      <div>
        <label className="text-sm font-medium">伤害显示类型</label>
        <Select value={damageDisplayType} onChange={(e) => setDamageDisplayType(e.target.value as DamageDisplayType)}>
          <option value="single_damage">单次伤害</option>
          <option value="combo_repeated_damage">连击伤害</option>
        </Select>
      </div>
      {damageDisplayType !== "combo_repeated_damage" ? <NumberField label="伤害值" value={damageValue} onChange={setDamageValue} /> : null}
      {damageDisplayType === "combo_repeated_damage" ? (
        <div className="grid grid-cols-2 gap-3"><NumberField label="单段伤害" value={perHitDamage} onChange={setPerHitDamage} /><NumberField label="连击次数" value={hitCount} onChange={(value) => { setHitCount(value); setHitCountManuallyEdited(true); }} /></div>
      ) : null}
      {defenderSide === "self" ? (
        <div className="rounded-xl border bg-raised/60 p-3 text-xs text-muted-foreground">
          我方受击会按当前 HP 扣减本次伤害值，不需要额外填写剩余血量。
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3">
          <NumberMaybeField label="受击前 HP%" value={hpBefore} onChange={setHpBefore} />
          <NumberMaybeField label="受击后 HP%" value={hpAfter} onChange={setHpAfter} />
        </div>
      )}
      <div className="space-y-3 rounded-2xl border bg-raised/60 p-3 text-sm">
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={syncObservation} onChange={(e) => setSyncObservation(e.target.checked)} />
          <span>同步写入实时面板估计观察</span>
        </label>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={resolveRules} onChange={(e) => setResolveRules(e.target.checked)} disabled={!syncObservation} />
          <span>启用后端规则解析（技能、本系、克制、应对）</span>
        </label>
        <NumberField label="伤害容差" value={damageTolerance} onChange={setDamageTolerance} />
        {syncObservation && observationPayloads.length === 0 ? (
          <div className="rounded-xl border border-warning/25 bg-warning/10 p-2 text-xs text-warning">
            当前缺少可用于反推的技能、敌方目标、伤害值或面板信息，本次只会记录事件。
          </div>
        ) : null}
      </div>
      {mutation.error ? <div className="rounded-xl border border-destructive/25 bg-destructive/10 p-2 text-xs text-destructive">提交失败：{String((mutation.error as Error).message)}</div> : null}
      <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="备注" />
      <SubmitButton loading={mutation.isPending} />
    </form>
  );
}

interface DamageObservationBuildInput {
  syncObservation: boolean;
  resolveRules: boolean;
  damageDisplayType: DamageDisplayType;
  battleId: string;
  attackerSide: Side;
  defenderSide: Side;
  attackerElfId?: string | null;
  defenderElfId?: string | null;
  attackerPanelStats: PanelStatsInput | null;
  defenderPanelStats: PanelStatsInput | null;
  skillId?: string | null;
  defenseSkillId?: string | null;
  responseAttackSuccess?: boolean | null;
  responseDefenseSuccess?: boolean | null;
  responseStatusSuccess?: boolean | null;
  observedTotalDamage: number;
  damageTolerance: number;
  hpBefore: number | null;
  hpAfter: number | null;
  hitCount: number;
}

function buildDamageObservationPayloads(input: DamageObservationBuildInput): ObservationCreate[] {
  if (!input.syncObservation || input.observedTotalDamage <= 0) return [];
  if (!input.skillId) return [];

  const enemyElfId = input.attackerSide === "enemy" ? input.attackerElfId : input.defenderElfId;
  if (!enemyElfId) return [];

  const enemyIsAttacker = input.attackerSide === "enemy";
  const payload: Record<string, unknown> = {
    ...buildDamageObservationPayloadV1({
      resolveRules: input.resolveRules,
      attackerSide: input.attackerSide,
      defenderSide: input.defenderSide,
      attackerElfId: input.attackerElfId,
      defenderElfId: input.defenderElfId,
      attackerPanelStats: input.attackerPanelStats,
      defenderPanelStats: input.defenderPanelStats,
      skillId: input.skillId,
      defenseSkillId: input.defenseSkillId,
      responseAttackSuccess: input.responseAttackSuccess,
      responseDefenseSuccess: input.responseDefenseSuccess,
      responseStatusSuccess: input.responseStatusSuccess,
      observedDamageValue: input.observedTotalDamage,
      damageTolerance: input.damageTolerance,
      hitCount: input.hitCount,
    }),
    skill_confirmed: Boolean(input.skillId),
    damage_display_type: input.damageDisplayType,
  };

  if (enemyIsAttacker) {
    if (!input.defenderPanelStats) return [];
  } else {
    if (!input.attackerPanelStats) return [];
  }

  const observations: ObservationCreate[] = [{
    enemy_elf_id: enemyElfId,
    observation_type: "damage_value",
    observed_value: input.observedTotalDamage,
    payload,
  }];

  if (!enemyIsAttacker && input.hpBefore !== null && input.hpAfter !== null) {
    const hpPercentDelta = Number((input.hpBefore - input.hpAfter).toFixed(4));
    const matching = payload.matching;
    const observed = payload.observed;
    observations.push({
      enemy_elf_id: enemyElfId,
      observation_type: "hp_percent_delta",
      observed_value: hpPercentDelta,
      payload: {
        ...payload,
        observed_hp_percent_before: input.hpBefore,
        observed_hp_percent_after: input.hpAfter,
        percent_display_mode: integerPercentPair(input.hpBefore, input.hpAfter)
          ? "floor_remaining_percent"
          : undefined,
        matching: {
          ...(typeof matching === "object" && matching !== null
            ? matching
            : {}),
          percent_tolerance: 0,
        },
        observed: {
          ...(typeof observed === "object" && observed !== null
            ? observed
            : {}),
          hp_percent_delta: hpPercentDelta,
        },
      },
    });
  }

  return observations;
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

function normalizeHpPercent(value?: number | null): number | null {
  if (value === null || value === undefined) return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function integerPercentPair(before: number, after: number): boolean {
  return Number.isInteger(before) && Number.isInteger(after);
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

function EffectForm({ battleId, state, defaultSide, onDone }: { battleId: string; state: { elves: BattleElfStateDict[]; battle: { turn_number: number; self_active_elf_id?: string | null; enemy_active_elf_id?: string | null } }; defaultSide?: Side | null; onDone: () => void }) {
  const [effectId, setEffectId] = useState<string | null>(null);
  const [selectedEffect, setSelectedEffect] = useState<EffectDefinitionOut | null>(null);
  const [ownerScope, setOwnerScope] = useState("elf");
  const [ownerSide, setOwnerSide] = useState<Side>(defaultSide ?? "self");
  const [layers, setLayers] = useState(1);
  const [remainingTurns, setRemainingTurns] = useState<number | "">("");
  const ownerElfId = ownerSide === "self" ? state.battle.self_active_elf_id : state.battle.enemy_active_elf_id;
  const layerSummary = buildEffectLayerSummary(selectedEffect ?? undefined, layers);
  const updateLayers = (value: number) => {
    const normalized = Math.max(1, value || 1);
    setLayers(selectedEffect?.max_layers ? Math.min(normalized, selectedEffect.max_layers) : normalized);
  };
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
    <form className="space-y-4" onSubmit={(e) => {
      e.preventDefault();
      if (!effectId) return;
      mutation.mutate();
    }}>
      <div className="rounded-2xl border bg-raised/60 p-3 text-sm text-foreground/80">
        这里只用于施加、更新或修正最终状态/天气结果。灼烧、中毒、棘刺等可见扣血请在“记录状态技能已发动”的抽屉里勾选“状态/印记结算伤害”录入，避免和普通状态修正混在一起。
      </div>
      <EffectSearchSelect
        label="状态"
        value={effectId}
        onChange={(id, item) => {
          setEffectId(id);
          setSelectedEffect(item);
          setLayers(item.default_layers ?? 1);
          setOwnerScope(item.owner_scope || "elf");
        }}
        resultsMode="focus"
      />
      <div><label className="text-sm font-medium">归属范围</label><Select value={ownerScope} onChange={(e) => setOwnerScope(e.target.value)}><option value="elf">精灵</option><option value="side">队伍侧</option><option value="field">全战场</option><option value="skill_slot">技能槽</option><option value="turn">当前回合</option></Select></div>
      {ownerScope !== "field" ? <SideSelect label="归属方" value={ownerSide} onChange={setOwnerSide} /> : null}
      <div className="grid grid-cols-2 gap-3">
        <NumberField label="层数" value={layers} onChange={updateLayers} />
        <NumberMaybeField label="剩余回合" value={remainingTurns} onChange={setRemainingTurns} />
      </div>
      {selectedEffect ? (
        <div className="rounded-2xl border bg-raised/60 p-3 text-xs text-foreground/80">
          <div className="font-medium text-foreground">层数预览</div>
          {layerSummary.hasStructuredRule ? (
            <div className="mt-1 space-y-1">
              <div>规则：{layerSummary.ruleTexts.join("；")}</div>
              <div>当前：{layerSummary.layerText}，最终 {layerSummary.finalTexts.join("；")}</div>
            </div>
          ) : (
            <div className="mt-1 text-muted-foreground">
              当前：{layerSummary.layerText}。该状态暂无结构化层数修正，只记录层数本身。
            </div>
          )}
        </div>
      ) : null}
      <SubmitButton loading={mutation.isPending} disabled={!effectId} />
    </form>
  );
}

function SwitchForm({ battleId, state, defaultSide, plannedAction, onDone }: { battleId: string; state: { elves: BattleElfStateDict[]; battle: { turn_number: number; self_active_elf_id?: string | null; enemy_active_elf_id?: string | null } }; defaultSide: Side; plannedAction?: PlannedActionPrefill; onDone: () => void }) {
  const [side, setSide] = useState<Side>(defaultSide);
  const [elfId, setElfId] = useState(plannedAction?.switchElfId ?? "");
  const activeElfId = side === "self" ? state.battle.self_active_elf_id : state.battle.enemy_active_elf_id;
  const candidates = useMemo(
    () => state.elves.filter((elf) => elf.side === side && elf.elf_id !== activeElfId),
    [state.elves, side, activeElfId],
  );
  useEffect(() => {
    if (!candidates.some((elf) => elf.elf_id === elfId)) {
      setElfId(candidates[0]?.elf_id ?? "");
    }
  }, [candidates, elfId]);
  const mutation = useMutation({ mutationFn: () => api.battles.switchElf(battleId, { side, elf_id: elfId, turn_number: state.battle.turn_number }), onSuccess: onDone });
  return (
    <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); mutation.mutate(); }}>
      <SideSelect label="切换方" value={side} onChange={(v) => { setSide(v); setElfId(""); }} />
      <div><label className="text-sm font-medium">新上场精灵</label><Select value={elfId} onChange={(e) => setElfId(e.target.value)}>{candidates.map((elf) => <option key={elf.elf_id} value={elf.elf_id}>{elf.elf_name ?? elf.elf_id}</option>)}</Select></div>
      <div className="rounded-2xl border bg-warning/10 p-3 text-sm text-warning">切换会由后端处理 clear_on_switch 状态：可切换清除的状态失效，不可清除的状态保留。</div>
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
type OptionalBoolInput = "" | "true" | "false";
function ResponseResultSelect({ label, value, onChange }: { label: string; value: OptionalBoolInput; onChange: (value: OptionalBoolInput) => void }) {
  return (
    <div>
      <label className="text-sm font-medium">{label}</label>
      <Select value={value} onChange={(e) => onChange(e.target.value as OptionalBoolInput)}>
        <option value="">未指定</option>
        <option value="false">失败</option>
        <option value="true">成功</option>
      </Select>
    </div>
  );
}
function ConditionFlagGroup({
  flags,
}: {
  flags: Array<[string, boolean, (value: boolean) => void]>;
}) {
  return (
    <div className="grid grid-cols-1 gap-2 rounded-2xl border bg-raised/60 p-3 text-sm sm:grid-cols-2">
      {flags.map(([label, checked, onChange]) => (
        <label key={label} className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={checked}
            onChange={(event) => onChange(event.target.checked)}
          />
          <span>{label}</span>
        </label>
      ))}
    </div>
  );
}
function optionalBool(value: OptionalBoolInput): boolean | undefined {
  if (value === "true") return true;
  if (value === "false") return false;
  return undefined;
}
function buildConditionFlags(flags: Record<string, boolean | undefined>): Record<string, boolean> {
  return Object.fromEntries(
    Object.entries(flags).filter((entry): entry is [string, boolean] => typeof entry[1] === "boolean"),
  );
}
function SubmitButton({ loading, disabled }: { loading: boolean; disabled?: boolean }) {
  return <Button className="w-full" type="submit" disabled={loading || disabled}>{loading ? "提交中..." : "提交事件"}</Button>;
}
