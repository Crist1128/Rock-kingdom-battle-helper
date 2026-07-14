import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight } from "lucide-react";
import { ApiError, api } from "@/lib/api";
import { useAppStore } from "@/store/useAppStore";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { ElfSearchSelect, SkillSearchSelect } from "@/components/EntitySearchSelect";
import { ElfCard } from "@/components/ElfCard";
import { StatGrid } from "@/components/StatGrid";
import { EstimatePanel, type EstimatePanelSelection } from "@/components/EstimatePanel";
import { EventTimeline } from "@/components/EventTimeline";
import { ActiveEffectsPanel } from "@/components/ActiveEffectsPanel";
import { ManualEventDrawer } from "@/components/ManualEventDrawer";
import { HealthBar } from "@/components/HealthBar";
import { cn, elementTypeName, phaseName, sideName, skillCategoryName } from "@/lib/utils";
import type { BattleEffectInstanceDict, BattleElfStateDict, BattleEventOut, BattleSkillSlotDict, BattleSpeedPreview, DamageEventCreateResult, ElfEvolutionStageOut, EndTurnResult, Side, SkillDefinitionOut, SpeedPreviewRow, SpeedPreviewTarget, StatBlock } from "@/types/api";

type PlannedActionKind = "unknown" | "attack_skill" | "defense_skill" | "status_skill" | "switch";

interface PlannedAction {
  kind: PlannedActionKind;
  skillId: string | null;
  skillName: string | null;
  switchElfId: string | null;
  switchElfName: string | null;
  cancelled: boolean;
  cancelReason: string | null;
}

type PlannedActions = Record<Side, PlannedAction>;
type DrawerActionMode = "skill" | "damage" | "resource" | "effect" | "switch";

function createEmptyAction(): PlannedAction {
  return {
    kind: "unknown",
    skillId: null,
    skillName: null,
    switchElfId: null,
    switchElfName: null,
    cancelled: false,
    cancelReason: null,
  };
}

function createEmptyActions(): PlannedActions {
  return {
    self: createEmptyAction(),
    enemy: createEmptyAction(),
  };
}

export function BattleWorkbenchPage() {
  const queryClient = useQueryClient();
  const { currentBattleId, openDrawer, setEstimatePanelElfId, estimatePanelElfId } = useAppStore();
  const [lastEndTurnResult, setLastEndTurnResult] = useState<EndTurnResult | null>(null);
  const [lastSkillEvent, setLastSkillEvent] = useState<BattleEventOut | null>(null);
  const [lastDamageEventResult, setLastDamageEventResult] = useState<DamageEventCreateResult | null>(null);
  const [plannedActions, setPlannedActions] = useState<PlannedActions>(() => createEmptyActions());
  const [enemyEstimateSelection, setEnemyEstimateSelection] = useState<EstimatePanelSelection | null>(null);
  const [damagePreviewRefreshing, setDamagePreviewRefreshing] = useState(false);
  const stateQuery = useQuery({
    queryKey: ["battle-state", currentBattleId],
    queryFn: () => api.battles.state(currentBattleId!),
    enabled: Boolean(currentBattleId),
    refetchInterval: 10_000,
  });
  const state = stateQuery.data;
  const selfElves = state?.elves.filter((elf) => elf.side === "self") ?? [];
  const enemyElves = state?.elves.filter((elf) => elf.side === "enemy") ?? [];
  const selfActive = selfElves.find((elf) => elf.elf_id === state?.battle.self_active_elf_id);
  const enemyActive = enemyElves.find((elf) => elf.elf_id === state?.battle.enemy_active_elf_id);
  const estimateElfId = estimatePanelElfId ?? state?.battle.enemy_active_elf_id;
  const canEndTurn = Boolean(currentBattleId && state && state.battle.phase === "battle");
  const activeEnemyEstimate =
    enemyEstimateSelection?.elfId === state?.battle.enemy_active_elf_id ? enemyEstimateSelection : null;
  const enemyEstimatedStats = activeEnemyEstimate?.stats ?? null;
  const activeDamagePreviewRefreshing =
    damagePreviewRefreshing && estimateElfId === state?.battle.enemy_active_elf_id;

  useEffect(() => {
    setPlannedActions(createEmptyActions());
  }, [currentBattleId, state?.battle.turn_number]);

  const finishBattle = useMutation({
    mutationFn: () => api.battles.finish(currentBattleId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["battle-state", currentBattleId] });
      queryClient.invalidateQueries({ queryKey: ["battles"] });
    },
  });

  const endTurn = useMutation({
    mutationFn: () => api.battles.endTurn(currentBattleId!, {}),
    onSuccess: (result) => {
      setLastEndTurnResult(result);
      queryClient.invalidateQueries({ queryKey: ["battle-state", currentBattleId] });
      queryClient.invalidateQueries({ queryKey: ["timeline", currentBattleId] });
      queryClient.invalidateQueries({ queryKey: ["enemy-estimate"] });
      queryClient.invalidateQueries({ queryKey: ["enemy-estimate-evidence"] });
      queryClient.invalidateQueries({ queryKey: ["battles"] });
    },
  });

  const returnToField = useMutation({
    mutationFn: ({ side, elfId }: { side: Side; elfId: string }) =>
      api.battles.switchElf(currentBattleId!, {
        side,
        elf_id: elfId,
        turn_number: state?.battle.turn_number,
        notes: "手动返场：离场清除后立即入场",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["battle-state", currentBattleId] });
      queryClient.invalidateQueries({ queryKey: ["timeline", currentBattleId] });
      queryClient.invalidateQueries({ queryKey: ["enemy-estimate"] });
      queryClient.invalidateQueries({ queryKey: ["enemy-estimate-evidence"] });
    },
  });

  const switchActiveElf = useMutation({
    mutationFn: ({ side, elfId }: { side: Side; elfId: string }) =>
      api.battles.switchElf(currentBattleId!, {
        side,
        elf_id: elfId,
        turn_number: state?.battle.turn_number,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["battle-state", currentBattleId] });
      queryClient.invalidateQueries({ queryKey: ["timeline", currentBattleId] });
      queryClient.invalidateQueries({ queryKey: ["enemy-estimate"] });
      queryClient.invalidateQueries({ queryKey: ["enemy-estimate-evidence"] });
    },
  });

  const changeRuntimeForm = useMutation({
    mutationFn: ({ stateId, effectiveElfId }: { stateId: string; effectiveElfId: string | null }) =>
      api.battles.changeRuntimeForm(currentBattleId!, stateId, {
        effective_elf_id: effectiveElfId,
        hp_policy: "keep_percent",
        reason: effectiveElfId ? "manual_runtime_form_change" : "restore_original_form",
        notes: "手动调整当前有效形态；不触发切换/返场副作用",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["battle-state", currentBattleId] });
      queryClient.invalidateQueries({ queryKey: ["timeline", currentBattleId] });
      queryClient.invalidateQueries({ queryKey: ["enemy-estimate"] });
      queryClient.invalidateQueries({ queryKey: ["enemy-estimate-evidence"] });
    },
    onError: (error) => {
      window.alert(`切换有效形态失败：${apiErrorText(error)}`);
    },
  });

  const requestEndTurn = () => {
    if (!currentBattleId || !state) return;
    if (!window.confirm(`确认结束第 ${state.battle.turn_number} 回合并执行回合末结算？`)) return;
    endTurn.mutate();
  };

  const requestFinishBattle = () => {
    if (!currentBattleId) return;
    if (!window.confirm("确认结束当前战斗？结束后仍可查看事件和实时估计记录。")) return;
    finishBattle.mutate();
  };

  const requestReturnToField = (side: Side, elfId: string) => {
    if (!currentBattleId || !state) return;
    const sideLabel = sideName(side);
    if (!window.confirm(`确认让${sideLabel}当前精灵执行返场？这会触发切换清除、入场结算和首回合机制。`)) return;
    returnToField.mutate({ side, elfId });
  };

  const requestSwitchActiveElf = (side: Side, elfId: string) => {
    if (!currentBattleId || !state) return;
    const currentActiveId = side === "self" ? state.battle.self_active_elf_id : state.battle.enemy_active_elf_id;
    if (elfId === currentActiveId) return;
    switchActiveElf.mutate({ side, elfId });
  };

  const quickSelectSkillAction = (side: Side, skill: Pick<BattleSkillSlotDict, "skill_id" | "skill_name" | "skill_category">) => {
    setPlannedActions((current) => ({
      ...current,
      [side]: {
        ...createEmptyAction(),
        kind: plannedKindFromSkillCategory(skill.skill_category),
        skillId: skill.skill_id,
        skillName: skill.skill_name ?? skill.skill_id,
      },
    }));
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold">战斗工作台</h1>
          <p className="mt-1 text-muted-foreground">当前 battle_id：{currentBattleId ?? "未选择"}</p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Badge variant="outline">{phaseName(state?.battle.phase)}</Badge>
          <Badge variant="secondary">回合 {state?.battle.turn_number ?? "--"}</Badge>
          <Badge variant="success">realtime estimate</Badge>
          <Button
            variant="outline"
            size="sm"
            disabled={!canEndTurn || endTurn.isPending}
            onClick={requestEndTurn}
          >
            {endTurn.isPending ? "结算中..." : "结束回合"}
          </Button>
          <Button
            variant="destructive"
            size="sm"
            disabled={!currentBattleId || !state || state.battle.phase === "finished" || state.battle.phase === "archived" || finishBattle.isPending}
            onClick={requestFinishBattle}
          >
            {finishBattle.isPending ? "结束中..." : "结束战斗"}
          </Button>
        </div>
      </div>

      {!currentBattleId ? <Card><CardContent className="pt-5 text-sm text-muted-foreground">请先在首页创建或选择战斗。</CardContent></Card> : null}
      {stateQuery.isLoading ? <Card><CardContent className="pt-5 text-sm text-muted-foreground">正在读取战斗状态...</CardContent></Card> : null}

      {state ? (
        <div className="grid grid-cols-[220px_minmax(0,1fr)_280px] gap-4">
          <div className="space-y-4">
            <TeamPanel title="我方队伍" elves={selfElves} activeElfId={state.battle.self_active_elf_id} onSwitch={(elfId) => { setEstimatePanelElfId(null); requestSwitchActiveElf("self", elfId); }} onReturn={(elfId) => requestReturnToField("self", elfId)} />
            <TeamPanel title="敌方队伍" elves={enemyElves} activeElfId={state.battle.enemy_active_elf_id} onSwitch={(elfId) => requestSwitchActiveElf("enemy", elfId)} onReturn={(elfId) => requestReturnToField("enemy", elfId)} onSelectEstimate={setEstimatePanelElfId} />
          </div>

          <div className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle>当前对位</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <SpeedPreviewPanel preview={state.speed_preview} />
                <div className="grid grid-cols-2 gap-4">
                  <ActiveSide
                    battleId={state.battle.battle_id}
                    title="我方上场"
                    elf={selfActive}
                    skillSlots={state.skill_slots.filter(
                      (slot) => slot.side === "self" && slot.elf_id === state.battle.self_active_elf_id,
                    )}
                    damagePreviewRefreshing={activeDamagePreviewRefreshing}
                  onRuntimeFormChange={(stateId, effectiveElfId) =>
                    changeRuntimeForm.mutate({ stateId, effectiveElfId })
                  }
                  runtimeFormChanging={changeRuntimeForm.isPending}
                  onSkillQuickSelect={(skill) => quickSelectSkillAction("self", skill)}
                />
                  <ActiveSide
                    battleId={state.battle.battle_id}
                    title="敌方上场"
                    elf={enemyActive}
                    skillSlots={state.skill_slots.filter(
                      (slot) => slot.side === "enemy" && slot.elf_id === state.battle.enemy_active_elf_id,
                    )}
                    estimatedStats={enemyEstimatedStats}
                    estimateSource={activeEnemyEstimate?.source ?? "unknown"}
                    estimateMatchedCount={activeEnemyEstimate?.matchedCount ?? 0}
                    estimateNatureName={activeEnemyEstimate?.natureName}
                    damagePreviewRefreshing={activeDamagePreviewRefreshing}
                  onRuntimeFormChange={(stateId, effectiveElfId) =>
                    changeRuntimeForm.mutate({ stateId, effectiveElfId })
                  }
                  runtimeFormChanging={changeRuntimeForm.isPending}
                  onSkillQuickSelect={(skill) => quickSelectSkillAction("enemy", skill)}
                />
                </div>
              </CardContent>
            </Card>

            <TurnActionPlanner
              state={state}
              plannedActions={plannedActions}
              onChange={setPlannedActions}
            />

            <TurnResolutionPanel
              plannedActions={plannedActions}
              canEndTurn={canEndTurn}
              endingTurn={endTurn.isPending}
              onOpenDrawer={openDrawer}
              onChange={setPlannedActions}
              onEndTurn={requestEndTurn}
              onRefresh={() => stateQuery.refetch()}
            />

            <Card>
              <CardHeader><CardTitle>统一状态系统</CardTitle></CardHeader>
              <CardContent>
                <ActiveEffectsPanel
                  battleId={currentBattleId!}
                  effects={state.active_effects}
                  turnNumber={state.battle.turn_number}
                />
              </CardContent>
            </Card>

            {lastEndTurnResult ? <EndTurnSummary result={lastEndTurnResult} /> : null}
            {lastSkillEvent ? <SkillOperationSummary event={lastSkillEvent} /> : null}
            {lastDamageEventResult ? <DamageEventSummary result={lastDamageEventResult} /> : null}

            <EventTimeline battleId={currentBattleId} compact />
          </div>

          <div className="space-y-4">
            <EstimatePanel
              battleId={currentBattleId}
              elfId={estimateElfId}
              onEstimateChange={setEnemyEstimateSelection}
              onDefaultConfigRefreshingChange={setDamagePreviewRefreshing}
            />
            <Card>
              <CardHeader><CardTitle>测试能力</CardTitle></CardHeader>
              <CardContent className="space-y-3 text-sm">
                <Capability label="普通攻击" value="最小公式可测" />
                <Capability label="状态/星陨" value="自动结算可测" />
                <Capability label="应对/防御" value="减伤上下文可测" />
                <Capability label="面板反推" value="实时估计" />
                <Capability label="实时估计" value="已接入" />
              </CardContent>
            </Card>
          </div>
        </div>
      ) : null}

      <ManualEventDrawer
        battleId={currentBattleId}
        state={state ? { battle: state.battle, elves: state.elves } : undefined}
        onSkillEventResult={setLastSkillEvent}
        onDamageEventResult={setLastDamageEventResult}
        plannedActionBySide={{
          self: {
            kind: plannedActions.self.kind,
            skillId: plannedActions.self.skillId,
            switchElfId: plannedActions.self.switchElfId,
          },
          enemy: {
            kind: plannedActions.enemy.kind,
            skillId: plannedActions.enemy.skillId,
            switchElfId: plannedActions.enemy.switchElfId,
          },
        }}
      />
    </div>
  );
}

function TurnActionPlanner({
  state,
  plannedActions,
  onChange,
}: {
  state: {
    battle: {
      self_active_elf_id?: string | null;
      enemy_active_elf_id?: string | null;
      turn_number: number;
    };
    elves: BattleElfStateDict[];
  };
  plannedActions: PlannedActions;
  onChange: (actions: PlannedActions) => void;
}) {
  const updateAction = (side: Side, action: PlannedAction) => {
    onChange({ ...plannedActions, [side]: action });
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <CardTitle>本回合行动选择</CardTitle>
          <Badge variant="outline">第 {state.battle.turn_number} 回合</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <ActionDraftEditor
            side="self"
            title="我方行动"
            state={state}
            action={plannedActions.self}
            onChange={(action) => updateAction("self", action)}
          />
          <ActionDraftEditor
            side="enemy"
            title="敌方行动"
            state={state}
            action={plannedActions.enemy}
            onChange={(action) => updateAction("enemy", action)}
          />
        </div>
        <div className="rounded-xl border bg-slate-50 p-3 text-xs text-muted-foreground">
          这里先记录双方本回合选择了什么，不会立刻写入后端事件。真正的伤害、状态、天气、切换和未出手结果，在下面“结算本回合”里按实际发生顺序录入。
        </div>
      </CardContent>
    </Card>
  );
}

function ActionDraftEditor({
  side,
  title,
  state,
  action,
  onChange,
}: {
  side: Side;
  title: string;
  state: {
    battle: {
      self_active_elf_id?: string | null;
      enemy_active_elf_id?: string | null;
    };
    elves: BattleElfStateDict[];
  };
  action: PlannedAction;
  onChange: (action: PlannedAction) => void;
}) {
  const activeElfId = side === "self" ? state.battle.self_active_elf_id : state.battle.enemy_active_elf_id;
  const activeElf = state.elves.find((elf) => elf.side === side && elf.elf_id === activeElfId);
  const switchCandidates = state.elves.filter((elf) => elf.side === side && elf.elf_id !== activeElfId);
  const needsSkill = action.kind === "attack_skill" || action.kind === "defense_skill" || action.kind === "status_skill";

  const updateKind = (kind: PlannedActionKind) => {
    onChange({
      ...createEmptyAction(),
      kind,
    });
  };

  const updateSkill = (id: string, skill: SkillDefinitionOut) => {
    onChange({
      ...action,
      skillId: id,
      skillName: skill.skill_name,
      cancelled: false,
      cancelReason: null,
    });
  };

  const updateSwitchTarget = (elfId: string) => {
    const elf = switchCandidates.find((item) => item.elf_id === elfId);
    onChange({
      ...action,
      switchElfId: elfId || null,
      switchElfName: elf?.elf_name ?? null,
      cancelled: false,
      cancelReason: null,
    });
  };

  return (
    <div className="space-y-3 rounded-xl border bg-white p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="font-semibold">{title}</div>
          <div className="text-xs text-muted-foreground">{battleElfDisplayName(activeElf) ?? activeElfId ?? "未选择上场精灵"}</div>
        </div>
        <Badge variant={action.kind === "unknown" ? "secondary" : "success"}>{plannedActionKindName(action.kind)}</Badge>
      </div>

      <div>
        <label className="text-sm font-medium">行动类型</label>
        <Select value={action.kind} onChange={(event) => updateKind(event.target.value as PlannedActionKind)}>
          <option value="unknown">未知 / 暂不记录</option>
          <option value="attack_skill">攻击技能</option>
          <option value="defense_skill">防御 / 应对技能</option>
          <option value="status_skill">状态 / 天气技能</option>
          <option value="switch">切换精灵</option>
        </Select>
      </div>

      {needsSkill ? (
        <SkillSearchSelect
          label="计划使用技能"
          value={action.skillId}
          onChange={updateSkill}
          elfId={activeElfId}
          resultsMode="focus"
        />
      ) : null}

      {action.kind === "switch" ? (
        <div>
          <label className="text-sm font-medium">计划切换到</label>
          <Select value={action.switchElfId ?? ""} onChange={(event) => updateSwitchTarget(event.target.value)}>
            <option value="">未选择</option>
            {switchCandidates.map((elf) => (
              <option key={elf.elf_id} value={elf.elf_id}>
                {elf.elf_name ?? elf.elf_id}
              </option>
            ))}
          </Select>
        </div>
      ) : null}

      {action.cancelled ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900">
          已标记未执行：{action.cancelReason ?? "未填写原因"}
        </div>
      ) : null}
    </div>
  );
}

function TurnResolutionPanel({
  plannedActions,
  canEndTurn,
  endingTurn,
  onOpenDrawer,
  onChange,
  onEndTurn,
  onRefresh,
}: {
  plannedActions: PlannedActions;
  canEndTurn: boolean;
  endingTurn: boolean;
  onOpenDrawer: (mode: DrawerActionMode, side?: Side | null) => void;
  onChange: (actions: PlannedActions) => void;
  onEndTurn: () => void;
  onRefresh: () => void;
}) {
  const updateAction = (side: Side, action: PlannedAction) => {
    onChange({ ...plannedActions, [side]: action });
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <CardTitle>结算本回合</CardTitle>
          <Badge variant="secondary">按实际发生顺序录入</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <ResolutionActionItem
            side="self"
            title="我方实际结果"
            action={plannedActions.self}
            onOpenDrawer={onOpenDrawer}
            onChange={(action) => updateAction("self", action)}
          />
          <ResolutionActionItem
            side="enemy"
            title="敌方实际结果"
            action={plannedActions.enemy}
            onOpenDrawer={onOpenDrawer}
            onChange={(action) => updateAction("enemy", action)}
          />
        </div>

        <div className="rounded-xl border bg-blue-50 p-3 text-xs text-blue-900">
          如果一方先手击杀、切换导致攻击没发生，先把对应行动标记为“未执行”，不要录入伤害。防御技能先按技能事件录入；之后另一方攻击伤害会继续使用后端自动继承的防御上下文。
        </div>

        <div className="grid grid-cols-2 gap-2 xl:grid-cols-4">
          <Button variant="outline" onClick={() => onOpenDrawer("resource", "self")}>治疗 / 能量</Button>
          <Button variant="outline" onClick={() => onOpenDrawer("effect", "self")}>我方状态</Button>
          <Button variant="outline" onClick={() => onOpenDrawer("effect", "enemy")}>敌方状态</Button>
          <Button variant="ghost" onClick={onRefresh}>刷新</Button>
        </div>
        <Button className="w-full" variant="secondary" disabled={!canEndTurn || endingTurn} onClick={onEndTurn}>
          {endingTurn ? "结算中..." : "结束回合并处理回合末效果"}
        </Button>
      </CardContent>
    </Card>
  );
}

function ResolutionActionItem({
  side,
  title,
  action,
  onOpenDrawer,
  onChange,
}: {
  side: Side;
  title: string;
  action: PlannedAction;
  onOpenDrawer: (mode: DrawerActionMode, side?: Side | null) => void;
  onChange: (action: PlannedAction) => void;
}) {
  const cancelled = action.cancelled;
  const markCancelled = (reason: string) => {
    onChange({
      ...action,
      cancelled: true,
      cancelReason: reason,
    });
  };
  const clearCancelled = () => {
    onChange({
      ...action,
      cancelled: false,
      cancelReason: null,
    });
  };

  return (
    <div className="space-y-3 rounded-xl border bg-white p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="font-semibold">{title}</div>
          <div className="text-xs text-muted-foreground">{plannedActionSummary(action)}</div>
        </div>
        <Badge variant={cancelled ? "warning" : action.kind === "unknown" ? "secondary" : "outline"}>
          {cancelled ? "未执行" : plannedActionKindName(action.kind)}
        </Badge>
      </div>

      {cancelled ? (
        <div className="space-y-2">
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900">
            原计划未写入真实技能/伤害事件。原因：{action.cancelReason ?? "--"}
          </div>
          <Button variant="outline" size="sm" onClick={clearCancelled}>恢复为待结算</Button>
        </div>
      ) : (
        <div className="space-y-2">
          {action.kind === "attack_skill" ? (
            <>
              <Button className="w-full" onClick={() => onOpenDrawer("damage", side)}>
                录入攻击伤害结果
              </Button>
              <Button className="w-full" variant="outline" onClick={() => onOpenDrawer("effect", side)}>
                补充攻击附带状态 / 天气
              </Button>
            </>
          ) : null}

          {action.kind === "defense_skill" ? (
            <Button className="w-full" onClick={() => onOpenDrawer("skill", side)}>
              记录防御 / 应对已发动
            </Button>
          ) : null}

          {action.kind === "status_skill" ? (
            <>
              <Button className="w-full" onClick={() => onOpenDrawer("skill", side)}>
                记录状态技能已发动
              </Button>
              <Button className="w-full" variant="outline" onClick={() => onOpenDrawer("effect", side)}>
                补充最终状态 / 天气结果
              </Button>
            </>
          ) : null}

          {action.kind === "switch" ? (
            <Button className="w-full" onClick={() => onOpenDrawer("switch", side)}>
              记录切换已发生
            </Button>
          ) : null}

          {action.kind === "unknown" ? (
            <div className="rounded-xl border bg-slate-50 p-3 text-xs text-muted-foreground">
              这方行动未知时可以先不录；等观察到真实结果后，再补充技能、伤害、状态或切换事件。
            </div>
          ) : null}

          {action.kind !== "unknown" ? (
            <div className="grid grid-cols-2 gap-2">
              <Button variant="outline" size="sm" onClick={() => markCancelled("被先手击倒")}>被击倒未出手</Button>
              <Button variant="outline" size="sm" onClick={() => markCancelled("目标变化或行动未发生")}>目标变化 / 未发生</Button>
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}

function plannedActionKindName(kind: PlannedActionKind) {
  if (kind === "attack_skill") return "攻击";
  if (kind === "defense_skill") return "防御";
  if (kind === "status_skill") return "状态";
  if (kind === "switch") return "切换";
  return "未知";
}

function plannedKindFromSkillCategory(category?: string | null): PlannedActionKind {
  if (category === "physical" || category === "magic") return "attack_skill";
  return "status_skill";
}

function plannedActionSummary(action: PlannedAction) {
  if (action.kind === "switch") return action.switchElfName ?? action.switchElfId ?? "计划切换，目标未选";
  if (action.kind === "attack_skill" || action.kind === "defense_skill" || action.kind === "status_skill") {
    return action.skillName ?? action.skillId ?? "计划使用技能，技能未选";
  }
  return "暂未记录行动意图";
}

function SkillOperationSummary({ event }: { event: BattleEventOut }) {
  const payload = parseEventPayload(event.payload_json);
  const results = Array.isArray(payload.effect_operation_results)
    ? payload.effect_operation_results.filter(isRecord)
    : [];
  const skillRuntime = asRecord(payload.skill_runtime);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <CardTitle>最近技能效果</CardTitle>
          <Badge variant={results.some((item) => item.status === "executed") ? "success" : "warning"}>
            {results.length > 0 ? `${results.length} 条操作` : "无结构化操作"}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <div className="grid grid-cols-3 gap-2">
          <Metric label="技能" value={compactEventValue(event.skill_id)} />
          <Metric label="行动方" value={sideName(event.actor_side)} />
          <Metric label="事件" value={compactEventValue(event.event_id)} />
        </div>
        {skillRuntime ? (
          <div className="grid grid-cols-3 gap-2">
            <Metric label="运行费用" value={String(skillRuntime.effective_energy_cost ?? "--")} />
            <Metric label="静态费用" value={String(skillRuntime.static_energy_cost ?? "--")} />
            <Metric label="技能槽" value={compactEventValue(skillRuntime.slot_id)} />
          </div>
        ) : null}
        {results.length > 0 ? (
          <div className="space-y-2">
            {results.map((item, index) => (
              <SkillOperationItem key={`${event.event_id}-${index}`} item={item} />
            ))}
          </div>
        ) : (
          <div className="rounded-xl border bg-slate-50 p-3 text-muted-foreground">
            这个技能没有可执行的结构化状态、天气或资源操作。
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function DamageEventSummary({ result }: { result: DamageEventCreateResult }) {
  const payload = parseEventPayload(result.battle_event.payload_json);
  const formulaContext = parseEventPayload(result.damage_event.formula_context_json);
  const ruleDetails = asRecord(formulaContext.rule_resolution_details);
  const damageReductions = asRecord(ruleDetails?.damage_reductions);
  const reductionItems = Array.isArray(damageReductions?.items)
    ? damageReductions.items.filter(isRecord)
    : [];
  const inference = result.inference_result;
  const defenseSkillId = payload.defense_skill_id ?? formulaContext.defense_skill_id;
  const defenseEventId = payload.defense_response_event_id ?? formulaContext.defense_response_event_id;
  const responseAttackSuccess = payload.response_attack_success ?? formulaContext.response_attack_success;
  const responseMultiplier = asRecord(ruleDetails?.response_multiplier);
  const powerMultiplier = asRecord(ruleDetails?.power_multiplier);
  const attackResponseRule = asRecord(ruleDetails?.attack_skill_response_rule);
  const conditionFlags = asRecord(payload.condition_flags) ?? asRecord(ruleDetails?.condition_flags);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <CardTitle>最近伤害反馈</CardTitle>
          <Badge variant={defenseSkillId ? "success" : "secondary"}>
            {defenseSkillId ? "已带入防御上下文" : "无防御上下文"}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <div className="grid grid-cols-3 gap-2">
          <Metric label="伤害事件" value={compactEventValue(result.damage_event.event_id)} />
          <Metric label="战斗事件" value={compactEventValue(result.battle_event.event_id)} />
          <Metric label="快照" value={compactEventValue(result.snapshot_id)} />
        </div>
        <div className="grid grid-cols-3 gap-2">
          <Metric label="防御技能" value={compactEventValue(defenseSkillId)} />
          <Metric label="来源事件" value={compactEventValue(defenseEventId)} />
          <Metric label="应对攻击" value={formatOptionalBool(responseAttackSuccess)} />
        </div>
        {attackResponseRule || responseMultiplier || powerMultiplier ? (
          <div className="grid grid-cols-3 gap-2">
            <Metric label="攻击应对" value={String(attackResponseRule?.target ?? "--")} />
            <Metric label="应对倍数" value={String(responseMultiplier?.value ?? "--")} />
            <Metric label="威力倍数" value={String(powerMultiplier?.value ?? "--")} />
          </div>
        ) : null}
        {conditionFlags ? (
          <FlagList title="条件标记" flags={conditionFlags} />
        ) : null}
        {reductionItems.length > 0 ? (
          <div className="space-y-2">
            {reductionItems.map((item, index) => (
              <div key={`${result.damage_event.event_id}-reduction-${index}`} className="rounded-xl border bg-white p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="success">减伤 {String(item.reduction ?? "--")}</Badge>
                  <Badge variant="outline">{String(item.source_name ?? item.source_id ?? "--")}</Badge>
                  {item.condition ? <Badge variant="secondary">{String(item.condition)}</Badge> : null}
                </div>
                <div className="mt-2 text-xs text-muted-foreground">
                  来源：{String(item.source_type ?? "--")}，目标：{String(item.target ?? "--")}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="rounded-xl border bg-slate-50 p-3 text-muted-foreground">
            本次伤害没有解析出可用减伤项；若你刚刚记录了防御技能，请确认伤害发生在同一回合、受击方一致，且防御技能规则已入库。
          </div>
        )}
        <div className="grid grid-cols-3 gap-2">
          <Metric label="推导状态" value={String(inference.status ?? "--")} />
          <Metric label="推导属性" value={String(inference.inferred_stat_count ?? "--")} />
          <Metric label="未知因素" value={String(inference.unknown_factor_count ?? "--")} />
        </div>
      </CardContent>
    </Card>
  );
}

function FlagList({ title, flags }: { title: string; flags: Record<string, unknown> }) {
  const enabledFlags = Object.entries(flags).filter(([, value]) => value === true);
  if (enabledFlags.length === 0) {
    return null;
  }
  return (
    <div className="rounded-xl border bg-slate-50 p-3">
      <div className="text-xs font-medium text-muted-foreground">{title}</div>
      <div className="mt-2 flex flex-wrap gap-2">
        {enabledFlags.map(([key]) => (
          <Badge key={key} variant="secondary">
            {formatConditionFlagName(key)}
          </Badge>
        ))}
      </div>
    </div>
  );
}

function SkillOperationItem({ item }: { item: Record<string, unknown> }) {
  const status = String(item.status ?? "unknown");
  const variant = status === "executed" ? "success" : status === "skipped" ? "secondary" : "warning";
  return (
    <div className="rounded-xl border bg-white p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={variant}>{formatOperationStatus(status)}</Badge>
        <Badge variant="outline">{String(item.operation ?? "--")}</Badge>
        {item.effect_name ? <span className="font-semibold">{String(item.effect_name)}</span> : null}
        {!item.effect_name && item.effect_id ? <span className="font-semibold">{String(item.effect_id)}</span> : null}
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-muted-foreground">
        {item.target ? <span>目标：{String(item.target)}</span> : null}
        {item.owner_side ? <span>归属：{sideName(String(item.owner_side))}</span> : null}
        {item.owner_elf_id ? <span>精灵：{compactEventValue(item.owner_elf_id)}</span> : null}
        {item.effect_instance_id ? <span>实例：{compactEventValue(item.effect_instance_id)}</span> : null}
        {item.layers_before !== undefined || item.layers_after !== undefined ? (
          <span>
            层数：{String(item.layers_before ?? "--")} -&gt; {String(item.layers_after ?? "--")}
          </span>
        ) : null}
        {item.reason ? <span>原因：{String(item.reason)}</span> : null}
        {item.condition ? <span>条件：{String(item.condition)}</span> : null}
      </div>
      {Array.isArray(item.removed_effects) && item.removed_effects.length > 0 ? (
        <div className="mt-2 text-xs text-muted-foreground">
          替换移除：{item.removed_effects.filter(isRecord).map((effect) => String(effect.effect_id ?? "--")).join("、")}
        </div>
      ) : null}
      {Array.isArray(item.changed_effects) && item.changed_effects.length > 0 ? (
        <div className="mt-2 text-xs text-muted-foreground">
          层数变更：
          {item.changed_effects
            .filter(isRecord)
            .map((effect) => `${String(effect.effect_id ?? "--")} ${String(effect.layers_before ?? "--")}→${String(effect.layers_after ?? "--")}`)
            .join("、")}
        </div>
      ) : null}
    </div>
  );
}

function parseEventPayload(rawJson?: string | null): Record<string, unknown> {
  if (!rawJson) return {};
  try {
    const value = JSON.parse(rawJson) as unknown;
    return isRecord(value) ? value : {};
  } catch {
    return {};
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return isRecord(value) ? value : null;
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

function formatOptionalBool(value: unknown) {
  if (value === true) return "成功";
  if (value === false) return "失败";
  return "未指定";
}

function formatConditionFlagName(value: string) {
  const names: Record<string, string> = {
    actor_moves_before_target: "先于目标行动",
    actor_moves_after_target: "后于目标行动",
    target_switched_this_turn: "目标本回合切换",
    defender_switched_this_turn: "防御方本回合切换",
    self_switched_this_turn: "我方本回合切换",
    enemy_switched_this_turn: "敌方本回合切换",
    post_damage_defeat_condition: "本次击败目标",
  };
  return names[value] ?? value;
}

function formatOperationStatus(status: string) {
  if (status === "executed") return "已执行";
  if (status === "skipped") return "跳过";
  if (status === "unknown") return "待确认";
  return status;
}

function compactEventValue(value: unknown) {
  if (typeof value !== "string" || !value) return "--";
  return value.length > 16 ? `${value.slice(0, 10)}...` : value;
}

function EndTurnSummary({ result }: { result: EndTurnResult }) {
  const eventCount = result.settlement_events.length;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <CardTitle>最近回合结算</CardTitle>
          <Badge variant={result.settlement_status === "settled" ? "success" : "warning"}>
            {result.settlement_status}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        <div className="grid grid-cols-4 gap-2">
          <Metric label="已结回合" value={result.ended_turn_number} />
          <Metric label="当前回合" value={result.next_turn_number} />
          <Metric label="结算事件" value={eventCount} />
          <Metric label="快照" value={result.snapshot_id.slice(0, 8)} />
        </div>
        {eventCount > 0 ? (
          <div className="space-y-2">
            {result.settlement_events.slice(0, 6).map((item, index) => (
              <SettlementEventItem key={`${result.battle_event.event_id}-${index}`} item={item} />
            ))}
            {eventCount > 6 ? (
              <div className="text-xs text-muted-foreground">还有 {eventCount - 6} 条结算事件，请在时间线查看完整记录。</div>
            ) : null}
          </div>
        ) : (
          <div className="rounded-xl border bg-muted/40 p-3 text-muted-foreground">
            本回合没有产生自动结算事件。
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function SettlementEventItem({ item }: { item: Record<string, unknown> }) {
  const observationResult =
    typeof item.observation_result === "object" && item.observation_result !== null
      ? (item.observation_result as Record<string, unknown>)
      : null;

  return (
    <div className="rounded-xl border bg-white p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline">{String(item.status ?? "event")}</Badge>
        {item.settlement_phase ? <Badge variant="secondary">{String(item.settlement_phase)}</Badge> : null}
        {item.effect_id ? <span className="font-semibold">{String(item.effect_id)}</span> : null}
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-muted-foreground">
        {item.target_side ? <span>目标：{String(item.target_side)} / {String(item.target_elf_id ?? "--")}</span> : null}
        {item.damage_value !== undefined ? <span>伤害：{String(item.damage_value)}</span> : null}
        {item.layers_before !== undefined || item.layers_after !== undefined ? (
          <span>
            层数：{String(item.layers_before ?? "--")} -&gt; {String(item.layers_after ?? "--")}
          </span>
        ) : null}
        {item.reason ? <span>原因：{String(item.reason)}</span> : null}
      </div>
      {observationResult ? (
        <div className="mt-2 text-xs text-muted-foreground">
          实时估计反馈：推导 {String(observationResult.inferred_stat_count ?? "--")} 项，影响{" "}
          {Array.isArray(observationResult.affected_stats)
            ? observationResult.affected_stats.join("、") || "--"
            : "--"}
        </div>
      ) : null}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-xl border bg-white p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 font-semibold">{value}</div>
    </div>
  );
}

function Capability({ label, value, muted = false }: { label: string; value: string; muted?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-2xl border bg-white p-3">
      <span className="text-muted-foreground">{label}</span>
      <span className={muted ? "font-semibold text-amber-700" : "font-semibold text-emerald-700"}>{value}</span>
    </div>
  );
}

function TeamPanel({
  title,
  elves,
  activeElfId,
  onSwitch,
  onReturn,
  onSelectEstimate,
}: {
  title: string;
  elves: BattleElfStateDict[];
  activeElfId?: string | null;
  onSwitch: (elfId: string) => void;
  onReturn?: (elfId: string) => void;
  onSelectEstimate?: (elfId: string) => void;
}) {
  return (
    <Card>
      <CardHeader><CardTitle>{title}</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        {elves.map((elf) => (
          <ElfCard
            key={elf.elf_id}
            elf={elf}
            active={elf.elf_id === activeElfId}
            onSwitch={() => onSwitch(elf.elf_id)}
            onReturn={onReturn ? () => onReturn(elf.elf_id) : undefined}
            onSelectEstimate={onSelectEstimate ? () => onSelectEstimate(elf.elf_id) : undefined}
          />
        ))}
      </CardContent>
    </Card>
  );
}

function SkillSlotRuntimeList({
  battleId,
  ownerSide,
  skillSlots,
  damagePreviewRefreshing = false,
  onSkillQuickSelect,
}: {
  battleId: string;
  ownerSide?: Side;
  skillSlots: BattleSkillSlotDict[];
  damagePreviewRefreshing?: boolean;
  onSkillQuickSelect?: (skill: Pick<BattleSkillSlotDict, "skill_id" | "skill_name" | "skill_category">) => void;
}) {
  const [extraSkillId, setExtraSkillId] = useState<string | null>(null);
  const [extraSkill, setExtraSkill] = useState<SkillDefinitionOut | null>(null);
  const isEnemy = ownerSide === "enemy";
  const sortedSlots = [...skillSlots].sort((a, b) => a.slot_index - b.slot_index);
  const primarySlots = Array.from({ length: 4 }, (_, index) => {
    return sortedSlots.find((slot) => slot.slot_index === index) ?? null;
  });
  const runtimeExtraSlots = sortedSlots.filter((slot) => slot.slot_index >= 4);
  const attackerElementTypes = skillSlots.find((slot) => slot.attacker_element_types)?.attacker_element_types ?? [];
  const extraPreview = extraSkill ? buildStaticSkillPreview(extraSkill, attackerElementTypes) : null;
  const emptyText = isEnemy ? "开局未知；录入敌方使用技能或敌方伤害事件后会自动填入。" : "未配置携带技能";
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-semibold">{isEnemy ? "敌方技能槽" : "携带技能"}</span>
        {isEnemy ? <Badge variant="outline">开局未知</Badge> : null}
      </div>
      <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
        {primarySlots.map((slot, index) => (
          <SkillSlotCard
            key={slot?.slot_id ?? `empty-${index}`}
            label={isEnemy ? (slot ? `已发现 ${index + 1}` : `未知 ${index + 1}`) : `携带 ${index + 1}`}
            slot={slot}
            battleId={battleId}
            emptyText={emptyText}
            damagePreviewRefreshing={damagePreviewRefreshing}
            onSkillQuickSelect={onSkillQuickSelect}
          />
        ))}
      </div>
      <div className="rounded-xl border bg-white p-3">
        <div className="mb-2 flex items-center justify-between gap-2">
          <span className="text-xs font-semibold">{isEnemy ? "敌方额外技能" : "临时技能"}</span>
          <Badge variant="outline">第 5 槽</Badge>
        </div>
        {runtimeExtraSlots.length > 0 ? (
          <div className="mb-3 space-y-2">
            {runtimeExtraSlots.map((slot, index) => (
              <SkillSlotCard
                key={slot.slot_id}
                label={`${isEnemy ? "已发现额外" : "已确认额外"} ${index + 1}`}
                slot={slot}
                battleId={battleId}
                emptyText={emptyText}
                damagePreviewRefreshing={damagePreviewRefreshing}
                onSkillQuickSelect={onSkillQuickSelect}
              />
            ))}
          </div>
        ) : null}
        <SkillSearchSelect
          label={isEnemy ? "选择敌方额外技能" : "选择临时技能"}
          value={extraSkillId}
          onChange={(id, item) => {
            setExtraSkillId(id);
            setExtraSkill(item);
          }}
          placeholder={isEnemy ? "搜索敌方战斗中额外获得或变换出的技能" : "搜索战斗中额外获得或变换出的技能"}
          resultsMode="focus"
        />
        {extraPreview ? (
          <div className="mt-2 space-y-2">
            {shouldShowSkillEffectPreview(
              extraSkill?.skill_category,
              extraSkill?.raw_description,
              extraSkill?.effect_operations_json,
            ) ? (
              <SkillEffectPreviewPanel
                description={extraSkill?.raw_description}
                rawOperationsJson={extraSkill?.effect_operations_json}
              />
            ) : null}
            <SkillPowerPreviewLine preview={extraPreview} />
            {onSkillQuickSelect ? (
              <Button
                className="h-7 w-full"
                size="sm"
                variant="outline"
                type="button"
                onClick={() => {
                  if (!extraSkill) return;
                  onSkillQuickSelect({
                    skill_id: extraSkill.skill_id,
                    skill_name: extraSkill.skill_name,
                    skill_category: extraSkill.skill_category,
                  });
                }}
              >
                选为本回合行动
              </Button>
            ) : null}
          </div>
        ) : (
          <div className="mt-2 text-xs text-muted-foreground">
            {isEnemy
              ? "这里只用于手动预览敌方额外技能；真正记录请在敌方使用技能或造成伤害时录入技能。"
              : "用于记录变换、复制或额外获得的技能；当前仅作为工作台选择槽，不写入战斗状态。"}
          </div>
        )}
      </div>
    </div>
  );
}

function SkillSlotCard({
  label,
  slot,
  battleId,
  emptyText = "未配置携带技能",
  damagePreviewRefreshing = false,
  onSkillQuickSelect,
}: {
  label: string;
  slot: BattleSkillSlotDict | null;
  battleId: string;
  emptyText?: string;
  damagePreviewRefreshing?: boolean;
  onSkillQuickSelect?: (skill: Pick<BattleSkillSlotDict, "skill_id" | "skill_name" | "skill_category">) => void;
}) {
  const queryClient = useQueryClient();
  const [runtimeExpanded, setRuntimeExpanded] = useState(false);
  const [powerDraft, setPowerDraft] = useState("");
  const updateRuntime = useMutation({
    mutationFn: ({ slotId, currentPower }: { slotId: string; currentPower: number | null }) =>
      api.battles.updateSkillSlotRuntime(battleId, slotId, {
        current_power: currentPower,
        notes: currentPower === null ? "手动清除技能槽威力覆盖" : "手动填写技能槽威力覆盖",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["battle-state", battleId] });
      queryClient.invalidateQueries({ queryKey: ["timeline", battleId] });
      queryClient.invalidateQueries({ queryKey: ["enemy-estimate"] });
      queryClient.invalidateQueries({ queryKey: ["enemy-estimate-evidence"] });
      setRuntimeExpanded(false);
    },
  });

  if (!slot) {
    return (
      <div className="min-h-28 rounded-xl border border-dashed bg-slate-50 p-3 text-xs text-muted-foreground">
        <div className="font-medium text-slate-700">{label}</div>
        <div className="mt-4">{emptyText}</div>
      </div>
    );
  }
  return (
    <div
      className={cn(
        "min-h-28 rounded-xl border border-slate-200 bg-gradient-to-br from-white to-slate-50/90 p-3 text-xs shadow-sm",
        onSkillQuickSelect
          && "cursor-pointer transition hover:scale-[1.015] hover:border-primary/60 hover:from-primary/5 hover:to-sky-50 hover:shadow-md focus:outline-none focus:ring-2 focus:ring-primary/40",
      )}
      role={onSkillQuickSelect ? "button" : undefined}
      tabIndex={onSkillQuickSelect ? 0 : undefined}
      onClick={() => onSkillQuickSelect?.(slot)}
      onKeyDown={(event) => {
        if (!onSkillQuickSelect) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSkillQuickSelect(slot);
        }
      }}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-600">
            {label}
          </div>
          <div className="mt-1.5 truncate text-[13px] font-semibold text-slate-950">
            {slot.skill_name ?? compactEventValue(slot.skill_id)}
          </div>
        </div>
        <Badge
          variant={slot.is_virtual ? "warning" : "outline"}
          className="shrink-0 px-1.5 py-0 text-[10px]"
        >
          {slot.is_virtual ? "补齐" : "运行"}
        </Badge>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-1 text-muted-foreground">
        <Badge variant="outline" className="border-slate-200 px-1.5 py-0 text-[10px]">
          {elementTypeName(slot.element_type)}
        </Badge>
        <Badge variant="outline" className="border-slate-200 px-1.5 py-0 text-[10px]">
          {skillCategoryName(slot.skill_category)}
        </Badge>
        {slot.cooldown_remaining ? (
          <Badge variant="outline" className="border-amber-200 bg-amber-50 px-1.5 py-0 text-[10px] text-amber-700">
            冷却 {slot.cooldown_remaining}
          </Badge>
        ) : null}
      </div>
      <SkillSlotEffectBadges effects={slot.skill_slot_effects ?? []} />
      <div className="mt-2 grid grid-cols-2 gap-2 rounded-lg border border-slate-200 bg-white/80 p-2 text-[10px]">
        <div>
          <div className="text-muted-foreground">费用</div>
          <div className="mt-0.5 font-semibold text-slate-900">
            {slot.effective_energy_cost ?? slot.current_energy_cost ?? slot.base_energy_cost ?? "--"}
          </div>
        </div>
        <div>
          <div className="text-muted-foreground">威力</div>
          <div className={cn(
            "mt-0.5 font-semibold",
            slot.current_power !== null && slot.current_power !== undefined
              ? "text-primary"
              : "text-slate-900",
          )}>
            {slot.current_power ?? slot.static_base_power ?? "--"}
            {slot.current_power !== null && slot.current_power !== undefined ? "（覆盖）" : ""}
          </div>
        </div>
      </div>
      <div
        className="mt-2"
        onClick={(event) => event.stopPropagation()}
        onKeyDown={(event) => event.stopPropagation()}
      >
        <button
          type="button"
          className="flex items-center gap-1 text-[10px] font-medium text-primary hover:underline"
          onClick={() => {
            setPowerDraft(slot.current_power !== null && slot.current_power !== undefined ? String(slot.current_power) : "");
            setRuntimeExpanded((current) => !current);
          }}
        >
          {runtimeExpanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          调整技能威力
        </button>
        {runtimeExpanded ? (
          <div className="mt-2 rounded-lg border border-primary/15 bg-primary/5 p-2">
            <div className="text-[10px] text-muted-foreground">
              手动填写后会优先参与理论伤害和伤害事件计算；留空并清除则回到技能基础威力。
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Input
                className="h-8 w-24"
                type="number"
                min={0}
                max={999}
                value={powerDraft}
                placeholder={slot.static_base_power !== null && slot.static_base_power !== undefined ? String(slot.static_base_power) : "威力"}
                onChange={(event) => setPowerDraft(event.target.value)}
              />
              <Button
                size="sm"
                className="h-8"
                disabled={updateRuntime.isPending}
                onClick={() => {
                  const trimmed = powerDraft.trim();
                  if (!trimmed) return;
                  const nextPower = Math.max(0, Math.min(999, Math.trunc(Number(trimmed))));
                  if (!Number.isFinite(nextPower)) return;
                  updateRuntime.mutate({ slotId: slot.slot_id, currentPower: nextPower });
                }}
              >
                保存
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="h-8"
                disabled={updateRuntime.isPending || slot.current_power === null || slot.current_power === undefined}
                onClick={() => updateRuntime.mutate({ slotId: slot.slot_id, currentPower: null })}
              >
                清除
              </Button>
            </div>
            {updateRuntime.error ? (
              <div className="mt-2 text-[11px] text-red-600">
                保存失败：{String((updateRuntime.error as Error).message)}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
      {shouldShowSkillEffectPreview(
        slot.skill_category,
        slot.skill_description,
        slot.effect_operations_json,
      ) ? (
        <SkillEffectPreviewPanel
          description={slot.skill_description}
          rawOperationsJson={slot.effect_operations_json}
        />
      ) : null}
      <SkillPowerPreviewLine
        preview={slot.power_preview}
        fallbackPower={slot.current_power ?? slot.static_base_power}
      />
      {damagePreviewRefreshing ? (
        <DamagePreviewRefreshingNotice />
      ) : (
        <>
          <SkillDamagePreviewPanel slot={slot} />
          <SkillTeamDamagePreviewPanel slot={slot} />
        </>
      )}
    </div>
  );
}

function DamagePreviewRefreshingNotice() {
  return (
    <div className="mt-2 rounded-lg border border-sky-200 bg-sky-50 px-2 py-1.5 text-[10px] text-sky-700">
      <span className="inline-flex items-center gap-2">
        <span className="h-2 w-2 animate-pulse rounded-full bg-sky-500" />
        理论伤害刷新中，暂时隐藏旧数值...
      </span>
    </div>
  );
}

function SkillEffectPreviewPanel({
  description,
  rawOperationsJson,
}: {
  description?: string | null;
  rawOperationsJson?: string | null;
}) {
  const displayDescription = description ?? originalDescriptionFromRawOperations(rawOperationsJson);
  return (
    <div className="mt-2 rounded-lg border border-slate-200 bg-white/80 px-2 py-1.5 text-[10px] leading-5 text-slate-700 shadow-sm">
      {displayDescription ?? "暂无原始技能描述"}
    </div>
  );
}

function shouldShowSkillEffectPreview(
  skillCategory?: string | null,
  description?: string | null,
  rawOperationsJson?: string | null,
) {
  return Boolean(
    description
    || rawOperationsJson
    || skillCategory === "status"
    || skillCategory === "change"
    || skillCategory === "support"
    || skillCategory === "状态"
    || skillCategory === "变化"
    || skillCategory === "辅助",
  );
}

function originalDescriptionFromRawOperations(rawOperationsJson?: string | null): string | null {
  if (!rawOperationsJson) return null;
  try {
    const operations = JSON.parse(rawOperationsJson);
    if (!Array.isArray(operations)) return null;
    const descriptions = operations
      .filter(isRecord)
      .map((operation) => asString(operation.raw_description) ?? asString(operation.notes))
      .filter((value): value is string => Boolean(value));
    return descriptions.length > 0 ? [...new Set(descriptions)].join("；") : null;
  } catch {
    return null;
  }
}

function SkillDamagePreviewPanel({ slot }: { slot: BattleSkillSlotDict }) {
  const [expanded, setExpanded] = useState(false);
  const preview = slot.damage_preview;
  const currentTarget = preview?.current_target ?? null;

  if (!preview || preview.status === "skill_definition_missing") {
    return <div className="mt-2 text-[10px] text-muted-foreground">理论伤害 --</div>;
  }
  if (preview.status === "not_attack_skill") {
    return <div className="mt-2 text-[10px] text-muted-foreground">非攻击技能，暂无理论伤害</div>;
  }
  if (!currentTarget) {
    return (
      <div className="mt-2 rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-[10px] text-muted-foreground">
        理论伤害 --{preview.reason ? `（${preview.reason}）` : ""}
      </div>
    );
  }

  return (
    <div className="mt-2 rounded-lg border border-emerald-100 bg-emerald-50/40 px-2 py-1.5 text-[10px]">
      <button
        type="button"
        className="flex w-full items-center justify-between gap-2 text-left"
        onClick={(event) => {
          event.stopPropagation();
          setExpanded((value) => !value);
        }}
      >
        <span className="flex min-w-0 items-center gap-1 text-emerald-800">
          {expanded ? <ChevronDown className="h-3.5 w-3.5 shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
          <span className="font-medium">理论伤害</span>
        </span>
        <span className="font-semibold text-emerald-700">{damageTargetText(currentTarget)}</span>
      </button>
      {expanded ? (
        <div className="mt-2 space-y-2 border-t border-emerald-100 pt-2">
          <div className="flex flex-wrap gap-x-2 gap-y-1 text-muted-foreground">
            <span>{currentTarget.elf_name ?? compactEventValue(currentTarget.elf_id)}</span>
            <span>HP {currentTarget.defender_max_hp ?? "--"}</span>
            <span>克制 x{String(currentTarget.multipliers?.type ?? "1")}</span>
            <span>本系 x{String(currentTarget.multipliers?.stab ?? "1")}</span>
            {(currentTarget.hit_count ?? 1) > 1 ? (
              <span>
                连击 {currentTarget.hit_count} 段
                {currentTarget.hit_count_source ? `（${currentTarget.hit_count_source}）` : ""}
              </span>
            ) : null}
            {(currentTarget.effective_use_count ?? 1) > 1 ? (
              <span>技能使用次数 {currentTarget.effective_use_count} 次</span>
            ) : null}
          </div>
          {currentTarget.unknown_factors?.length ? (
            <div className="text-amber-700">未纳入：{currentTarget.unknown_factors.join("、")}</div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function SkillTeamDamagePreviewPanel({ slot }: { slot: BattleSkillSlotDict }) {
  const [expanded, setExpanded] = useState(false);
  const preview = slot.damage_preview;
  const targets = preview?.targets ?? [];
  if (!preview || preview.status === "skill_definition_missing" || preview.status === "not_attack_skill") {
    return null;
  }
  if (targets.length <= 1) return null;

  return (
    <div className="mt-2 rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-[10px]">
      <button
        type="button"
        className="flex w-full items-center justify-between gap-2 text-left"
        onClick={(event) => {
          event.stopPropagation();
          setExpanded((value) => !value);
        }}
      >
        <span className="flex min-w-0 items-center gap-1 text-muted-foreground">
          {expanded ? <ChevronDown className="h-3.5 w-3.5 shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
          <span>全场伤害</span>
        </span>
      </button>
      {expanded ? (
        <div className="mt-2 space-y-1 border-t pt-2">
          {targets.map((target) => (
            <div key={target.elf_id} className="flex items-center justify-between gap-2">
              <span className="min-w-0 truncate">
                {target.elf_name ?? compactEventValue(target.elf_id)}
                {target.is_active_target ? "（上场）" : ""}
              </span>
              <span className="shrink-0 font-medium text-slate-900">{damageTargetText(target)}</span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function damageTargetText(target: NonNullable<BattleSkillSlotDict["damage_preview"]>["current_target"]) {
  if (!target || target.status !== "calculated") {
    const missing = target?.missing_parts?.length ? `缺 ${target.missing_parts.join("/")}` : "无法计算";
    return missing;
  }
  const percent = typeof target.damage_percent === "number" ? `${target.damage_percent}%` : "--";
  const useCount = target.effective_use_count ?? 1;
  if (useCount > 1) {
    const effectivePercent = typeof target.effective_total_damage_percent === "number"
      ? `${target.effective_total_damage_percent}%`
      : percent;
    return `${target.single_use_total_damage ?? target.damage_value ?? "--"}×${useCount}=${target.effective_total_damage ?? "--"} / ${effectivePercent}`;
  }
  if ((target.hit_count ?? 1) > 1) {
    return `${target.single_damage ?? "--"}×${target.hit_count}=${target.total_damage ?? target.damage_value ?? "--"} / ${percent}`;
  }
  return `${target.damage_value ?? "--"} / ${percent}`;
}

function SkillPowerPreviewLine({
  preview,
  fallbackPower,
}: {
  preview?: BattleSkillSlotDict["power_preview"];
  fallbackPower?: number | null;
}) {
  const [expanded, setExpanded] = useState(false);
  if (!preview || preview.status === "skill_definition_missing") {
    return <div className="mt-2 text-[10px] text-muted-foreground">威力预览 --</div>;
  }
  if (preview.status === "no_power") {
    return <div className="mt-2 text-[10px] text-muted-foreground">变化/状态技能，暂无威力</div>;
  }
  const multipliers = preview.multipliers ?? {};
  const effectivePower = preview.effective_display_power_text ?? preview.effective_display_power ?? fallbackPower ?? "--";
  return (
    <div className="mt-2 rounded-lg border border-violet-100 bg-violet-50/40 px-2 py-1.5 text-[10px]">
      <button
        type="button"
        className="flex w-full items-center justify-between gap-2 text-left"
        onClick={(event) => {
          event.stopPropagation();
          setExpanded((value) => !value);
        }}
      >
        <span className="flex min-w-0 items-center gap-1 text-violet-800">
          {expanded ? <ChevronDown className="h-3.5 w-3.5 shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
          <span className="font-medium">估算威力</span>
        </span>
        <span className="font-semibold text-violet-700">{effectivePower}</span>
      </button>
      {expanded ? (
        <div className="mt-2 flex flex-wrap gap-x-2 gap-y-1 border-t border-violet-100 pt-2 text-muted-foreground">
          <span>本系 x{multipliers.stab ?? "1"}</span>
          <span>攻防状态 x{multipliers.stat_stage ?? "1"}</span>
          <span>天气 x{multipliers.weather ?? "1"}</span>
          <span>威力状态 x{multipliers.skill_power ?? "1"}</span>
        </div>
      ) : null}
    </div>
  );
}

function buildStaticSkillPreview(
  skill: SkillDefinitionOut,
  attackerElementTypes: string[],
): BattleSkillSlotDict["power_preview"] {
  if (skill.base_power == null) {
    return {
      status: "no_power",
      base_power: null,
      effective_display_power: null,
      preview_scope: "temporary_skill_static_only",
    };
  }
  const stabMultiplier = skill.element_type && attackerElementTypes.includes(skill.element_type) ? 1.25 : 1;
  const effectivePower = skill.base_power * stabMultiplier;
  return {
    status: "resolved",
    base_power: skill.base_power,
    static_base_power: skill.base_power,
    effective_display_power: effectivePower,
    effective_display_power_text: String(effectivePower),
    preview_scope: "temporary_skill_static_only",
    multipliers: {
      stab: String(stabMultiplier),
      stat_stage: "1",
      weather: "1",
      skill_power: "1",
    },
  };
}

function SkillSlotEffectBadges({ effects }: { effects: BattleEffectInstanceDict[] }) {
  const activeEffects = effects.filter((effect) => effect.is_active !== false);
  if (activeEffects.length === 0) return null;
  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5">
      <span className="rounded-full bg-indigo-50 px-1.5 py-0.5 text-[10px] font-medium text-indigo-700">
        特性
      </span>
      <div className="flex flex-wrap gap-1">
        {activeEffects.map((effect) => {
          const name = typeof effect.effect_name === "string" && effect.effect_name
            ? effect.effect_name
            : effect.effect_id;
          const layers = Number(effect.layers ?? 1);
          const remaining = typeof effect.remaining_uses === "number"
            ? `剩${effect.remaining_uses}次`
            : "";
          const layerText = Number.isFinite(layers) && layers !== 1 ? ` ×${layers}` : "";
          const groupText = typeof effect.display_group === "string" && effect.display_group
            ? effect.display_group
            : "--";
          const polarityText = typeof effect.polarity === "string" && effect.polarity
            ? effect.polarity
            : "--";
          return (
            <span
              key={effect.instance_id}
              className="group relative inline-flex"
              tabIndex={0}
              onClick={(event) => event.stopPropagation()}
            >
              <Badge
                variant="outline"
                className="border-indigo-200 bg-white px-1.5 py-0 text-[10px] text-indigo-700 shadow-sm"
              >
                {name}{layerText}{remaining ? ` · ${remaining}` : ""}
              </Badge>
              <span className="pointer-events-none absolute bottom-full left-0 z-30 mb-2 hidden w-64 rounded-lg border border-indigo-100 bg-white p-2 text-[10px] leading-5 text-slate-700 shadow-lg group-hover:block group-focus:block">
                <span className="block font-semibold text-indigo-800">{name}{layerText}</span>
                <span className="mt-1 block text-slate-600">状态ID：{effect.effect_id}</span>
                <span className="block text-slate-600">层数：{Number.isFinite(layers) ? layers : "--"}</span>
                <span className="block text-slate-600">分组：{groupText} · 极性：{polarityText}</span>
                {remaining ? <span className="block text-slate-600">剩余使用：{effect.remaining_uses} 次</span> : null}
                <span className="mt-1 block border-t border-indigo-50 pt-1 text-indigo-700">
                  技能槽侧修正：绑定当前精灵的这个技能，通常在技能卡展示，不进入普通状态栏。
                </span>
              </span>
            </span>
          );
        })}
      </div>
    </div>
  );
}

function apiErrorText(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message || `请求失败（HTTP ${error.status}）`;
  }
  return error instanceof Error ? error.message : String(error);
}

function hasRuntimeFormDisplay(elf?: BattleElfStateDict | null): boolean {
  return Boolean(
    elf?.effective_form_source === "runtime_form"
    && typeof elf.effective_elf_id === "string"
    && elf.effective_elf_id !== elf.elf_id,
  );
}

function battleElfDisplayName(elf?: BattleElfStateDict | null): string | null {
  if (!elf) return null;
  if (hasRuntimeFormDisplay(elf)) {
    return elf.effective_elf_name ?? elf.effective_elf_id ?? elf.elf_name ?? elf.elf_id;
  }
  return elf.elf_name ?? elf.elf_id;
}

function RuntimeFormControl({
  elf,
  disabled,
  onRuntimeFormChange,
}: {
  elf: BattleElfStateDict;
  disabled?: boolean;
  onRuntimeFormChange?: (stateId: string, effectiveElfId: string | null) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [selectedElfId, setSelectedElfId] = useState<string | null>(
    typeof elf.runtime_form_elf_id === "string" ? elf.runtime_form_elf_id : elf.elf_id,
  );
  const evolutionChainQuery = useQuery({
    queryKey: ["elf", elf.elf_id, "evolution-chain"],
    queryFn: () => api.elves.evolutionChain(elf.elf_id),
    enabled: expanded && Boolean(elf.elf_id),
    retry: false,
  });

  useEffect(() => {
    setSelectedElfId(typeof elf.runtime_form_elf_id === "string" ? elf.runtime_form_elf_id : elf.elf_id);
  }, [elf.state_id, elf.runtime_form_elf_id, elf.elf_id]);

  if (!elf.state_id || !onRuntimeFormChange) return null;

  const isRuntimeForm = elf.effective_form_source === "runtime_form";
  const currentEffective = isRuntimeForm
    ? `${elf.effective_elf_name ?? elf.effective_elf_id}（原：${elf.elf_name ?? elf.elf_id}）`
    : "原始形态";
  const chainStages = evolutionChainQuery.data?.stages ?? [];
  const hasChainStages = chainStages.length > 0;
  const selectedStage = chainStages.find((stage) => stage.elf_id === selectedElfId);
  const applyRuntimeForm = (targetElfId: string | null) => {
    const effectiveElfId = targetElfId && targetElfId !== elf.elf_id ? targetElfId : null;
    const currentRuntimeElfId =
      isRuntimeForm && typeof elf.runtime_form_elf_id === "string" ? elf.runtime_form_elf_id : null;
    if (effectiveElfId === currentRuntimeElfId) return;
    onRuntimeFormChange(elf.state_id!, effectiveElfId);
  };
  const applySelected = () => applyRuntimeForm(selectedElfId);

  return (
    <div className="text-xs">
      <Button
        className="h-7 gap-1 px-2"
        size="sm"
        variant={isRuntimeForm ? "outline" : "ghost"}
        type="button"
        onClick={() => setExpanded((value) => !value)}
      >
        {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        有效形态：{currentEffective}
      </Button>
      {expanded ? (
        <div className="mt-2 rounded-xl border bg-slate-50 p-2">
          {hasChainStages ? (
            <RuntimeFormChainSelect
              stages={chainStages}
              originalElfId={elf.elf_id}
              value={selectedElfId}
              onChange={setSelectedElfId}
              onApply={applyRuntimeForm}
              disabled={disabled}
            />
          ) : (
            <>
              <div className="mb-2 rounded-lg border border-amber-200 bg-amber-50 px-2 py-1 text-[11px] text-amber-700">
                {evolutionChainQuery.isLoading
                  ? "正在加载进化链可选形态..."
                  : "暂未录入该精灵的进化链数据，保留全局搜索作为兜底。"}
              </div>
              <ElfSearchSelect
                label="选择有效形态"
                value={selectedElfId}
                onChange={(id) => setSelectedElfId(id)}
                placeholder="搜索兜底形态"
                resultsMode="focus"
              />
            </>
          )}
          {selectedStage ? (
            <div className="mt-2 rounded-lg border border-primary/20 bg-white px-2 py-1 text-[11px] text-primary">
              已选进化阶段 {selectedStage.stage_index}：{selectedStage.elf_name}
            </div>
          ) : null}
          <div className="mt-2 flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="outline"
              type="button"
              disabled={disabled || !selectedElfId}
              onClick={applySelected}
            >
              {disabled ? "切换中..." : "应用所选形态"}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              type="button"
              disabled={disabled || !isRuntimeForm}
              onClick={() => {
                setSelectedElfId(elf.elf_id);
                onRuntimeFormChange(elf.state_id!, null);
              }}
            >
              恢复原始形态
            </Button>
          </div>
          <div className="mt-1 text-muted-foreground">
            保留原有性格、资质与培养设置；只按有效形态重算面板，不触发切换、返场或入场副作用。
          </div>
        </div>
      ) : null}
    </div>
  );
}

function RuntimeFormChainSelect({
  stages,
  originalElfId,
  value,
  onChange,
  onApply,
  disabled,
}: {
  stages: ElfEvolutionStageOut[];
  originalElfId: string;
  value?: string | null;
  onChange: (elfId: string) => void;
  onApply?: (elfId: string) => void;
  disabled?: boolean;
}) {
  const handleSelect = (elfId: string) => {
    onChange(elfId);
    onApply?.(elfId);
  };

  return (
    <div className="space-y-2">
      <label className="text-sm font-medium">进化链形态</label>
      <Select
        value={value ?? originalElfId}
        disabled={disabled}
        onChange={(event) => handleSelect(event.target.value)}
      >
        {stages.map((stage) => (
          <option key={`${stage.chain_id}:${stage.elf_id}`} value={stage.elf_id}>
            {stage.stage_index}. {stage.elf_name}{stage.elf_id === originalElfId ? "（原始）" : ""}
          </option>
        ))}
      </Select>
      <div className="grid gap-1 rounded-xl border bg-white p-1">
        {stages.map((stage) => {
          const selected = stage.elf_id === value;
          return (
            <button
              key={`${stage.chain_id}:button:${stage.elf_id}`}
              type="button"
              disabled={disabled}
              className={cn(
                "flex items-center justify-between rounded-lg px-2 py-1.5 text-left transition hover:bg-muted",
                selected && "border border-primary bg-primary/10 text-primary",
                disabled && "cursor-not-allowed opacity-60",
              )}
              onClick={() => handleSelect(stage.elf_id)}
            >
              <span className="min-w-0 flex-1 truncate">
                {stage.stage_index}. {stage.elf_name}
              </span>
              <span className="ml-2 shrink-0 text-[10px] text-muted-foreground">
                速度种族 {stage.base_speed_talent}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function ActiveSide({
  battleId,
  title,
  elf,
  skillSlots = [],
  estimatedStats,
  estimateSource = "unknown",
  estimateMatchedCount = 0,
  estimateNatureName,
  damagePreviewRefreshing = false,
  onRuntimeFormChange,
  runtimeFormChanging = false,
  onSkillQuickSelect,
}: {
  battleId: string;
  title: string;
  elf?: BattleElfStateDict | null;
  skillSlots?: BattleSkillSlotDict[];
  estimatedStats?: StatBlock | null;
  estimateSource?: "default_config" | "expanded_config" | "base_talent" | "unknown";
  estimateMatchedCount?: number;
  estimateNatureName?: string | null;
  damagePreviewRefreshing?: boolean;
  onRuntimeFormChange?: (stateId: string, effectiveElfId: string | null) => void;
  runtimeFormChanging?: boolean;
  onSkillQuickSelect?: (skill: Pick<BattleSkillSlotDict, "skill_id" | "skill_name" | "skill_category">) => void;
}) {
  const hasRuntimeStats = hasPanelStats(elf?.panel_stats_json);
  const runtimeStats = statBlockFromStatsJson(elf?.panel_stats_json);
  const backendEffectiveStats = statBlockFromUnknown(elf?.effective_panel_stats);
  const displayEstimatedStats = !hasRuntimeStats ? estimatedStats ?? backendEffectiveStats : undefined;
  const hpStats = hasRuntimeStats ? runtimeStats ?? backendEffectiveStats : displayEstimatedStats;
  const hpSourceLabel = !hasRuntimeStats && hpStats ? "按当前估计配置显示" : null;
  const natureName =
    typeof elf?.nature_name === "string" && elf.nature_name
      ? elf.nature_name
      : estimateNatureName;
  const displayName = battleElfDisplayName(elf);
  const originalName = elf?.elf_name ?? elf?.elf_id;
  return (
    <div className="rounded-2xl border bg-white p-4">
      <div className="mb-2 flex items-center justify-between"><div className="font-semibold">{title}</div><Badge variant="outline">{sideName(elf?.side)}</Badge></div>
      {elf ? (
        <div className="space-y-3">
          <div>
            <div className="text-lg font-semibold">{displayName ?? elf.elf_id}</div>
            {hasRuntimeFormDisplay(elf) ? (
              <div className="text-xs text-muted-foreground">原始精灵：{originalName}</div>
            ) : null}
          </div>
          <div className="rounded-xl border bg-slate-50 p-2">
            <HealthBar
              currentHpValue={typeof elf.current_hp_value === "number" ? elf.current_hp_value : null}
              currentHpPercent={typeof elf.current_hp_percent === "number" ? elf.current_hp_percent : null}
              maxHp={typeof hpStats?.hp === "number" ? hpStats.hp : null}
              sourceLabel={hpSourceLabel}
            />
            <div className="mt-2 text-xs text-muted-foreground">能量 {elf.energy ?? 0}</div>
          </div>
          <div className="rounded-xl border bg-slate-50 p-2 text-xs text-muted-foreground">
            性格：<span className="font-medium text-slate-900">{natureName ?? "未知"}</span>
            {elf.nature_source ? <span className="ml-2">来源：{natureSourceName(String(elf.nature_source))}</span> : null}
          </div>
          <RuntimeFormControl
            elf={elf}
            disabled={runtimeFormChanging}
            onRuntimeFormChange={onRuntimeFormChange}
          />
          <StatGrid statsJson={hasRuntimeStats ? elf.panel_stats_json : undefined} stats={displayEstimatedStats} compact />
          <SkillSlotRuntimeList
            battleId={battleId}
            ownerSide={elf.side}
            skillSlots={skillSlots}
            damagePreviewRefreshing={damagePreviewRefreshing}
            onSkillQuickSelect={onSkillQuickSelect}
          />
          {!hasRuntimeStats && displayEstimatedStats ? (
            <div className="text-xs text-amber-700">
              {estimateSource === "expanded_config"
                ? `显示你选择的默认配置，命中 ${estimateMatchedCount} 项约束。`
                : estimateSource === "default_config"
                  ? "显示玩家默认配置面板，敌方真实六维尚未确认。"
                  : estimateSource === "base_talent"
                    ? "显示种族值占位面板，等待观测或默认配置。"
                    : "显示实时估计面板，敌方真实六维尚未确认。"}
            </div>
          ) : null}
          {!hasRuntimeStats && !displayEstimatedStats ? (
            <div className="text-xs text-muted-foreground">敌方真实六维未知，设置默认配置后可显示估计面板；后端会按当前推导约束校验保存。</div>
          ) : null}
        </div>
      ) : <div className="text-sm text-muted-foreground">未选择上场精灵。</div>}
    </div>
  );
}

function SpeedPreviewPanel({ preview }: { preview?: BattleSpeedPreview | null }) {
  const [expanded, setExpanded] = useState(false);
  if (!preview || preview.status !== "resolved" || !preview.self) {
    return (
      <div className="rounded-xl border border-sky-200 bg-sky-50 p-2 text-xs text-muted-foreground">
        速度观察：当前信息不足。
      </div>
    );
  }

  const activeRows = preview.active_enemy?.rows ?? [];
  const activeSummary = activeRows.length > 0
    ? activeRows
        .filter((row) =>
          row.source === "assumption_neutral_speed_10"
          || row.source === "assumption_positive_speed_10"
          || row.source === "enemy_default_panel"
          || row.source === "enemy_estimated_panel"
          || row.source === "runtime_state",
        )
        .slice(0, 2)
        .map((row) => `${row.label}：${speedRelationText(row)}`)
        .join("；")
    : "暂无敌方速度档位";

  return (
    <div className="rounded-xl border border-sky-200 bg-sky-50 p-2 text-xs">
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="h-auto w-full justify-start gap-1 px-1 py-1 text-left"
        onClick={() => setExpanded((value) => !value)}
      >
        {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        <span className="font-medium text-slate-900">
          速度观察：我方 {preview.self.current_speed ?? "--"}
        </span>
        <span className="truncate text-muted-foreground">{activeSummary}</span>
      </Button>

      {expanded ? (
        <div className="mt-2 space-y-3">
          <div className="flex flex-wrap gap-2 text-muted-foreground">
            <span>基础 {preview.self.base_speed ?? "--"}</span>
            <span>状态修正 {formatSigned(preview.self.speed_modifier ?? 0)}</span>
            <span>当前 {preview.self.current_speed ?? "--"}</span>
            {preview.self.unknown_factors?.length ? (
              <span className="text-amber-700">存在未计入速度因素</span>
            ) : null}
          </div>

          {preview.active_enemy ? (
            <SpeedPreviewTargetBlock title="当前敌方" target={preview.active_enemy} compact />
          ) : (
            <div className="text-muted-foreground">暂无当前敌方速度对比。</div>
          )}

          {(preview.enemy_team ?? []).length > 0 ? (
            <div className="space-y-2">
              <div className="font-medium text-slate-900">敌方全队</div>
              <div className="grid gap-2 md:grid-cols-2">
                {(preview.enemy_team ?? []).map((target) => (
                  <SpeedPreviewTargetBlock key={target.elf_id} target={target} compact />
                ))}
              </div>
            </div>
          ) : null}

          <div className="text-muted-foreground">
            默认按敌方速度资质 10，分别比较未加速性格和加速性格；这里只做观察，不写入速度反推。
          </div>
        </div>
      ) : null}
    </div>
  );
}

function SpeedPreviewTargetBlock({
  title,
  target,
  compact = false,
}: {
  title?: string;
  target: SpeedPreviewTarget;
  compact?: boolean;
}) {
  const rows = compact
    ? target.rows.filter((row) =>
        row.source === "enemy_default_panel"
        || row.source === "enemy_estimated_panel"
        || row.source === "runtime_state"
        || row.source === "assumption_neutral_speed_10"
        || row.source === "assumption_positive_speed_10",
      )
    : target.rows;
  return (
    <div className="rounded-lg border bg-white p-2">
      <div className="mb-1 flex items-center justify-between gap-2">
        <div className="font-medium text-slate-900">
          {title ? `${title}：` : ""}
          {target.effective_elf_name ?? target.elf_name ?? target.elf_id}
        </div>
        {target.is_active_target ? <Badge variant="secondary">上场</Badge> : null}
      </div>
      <div className="space-y-1">
        {rows.map((row) => (
          <div key={`${target.elf_id}-${row.source}`} className="flex justify-between gap-2">
            <span className="truncate text-muted-foreground">
              {row.label}
              {row.enemy_speed_modifier ? `（修正${formatSigned(row.enemy_speed_modifier)}）` : ""}
            </span>
            <span className={speedRelationClassName(row)}>{speedRelationText(row)}</span>
          </div>
        ))}
      </div>
      {target.unknown_factors?.length ? (
        <div className="mt-1 text-amber-700">有未计入速度因素</div>
      ) : null}
    </div>
  );
}

function speedRelationText(row: SpeedPreviewRow) {
  const closeText = row.is_close ? "（接近）" : "";
  if (row.relation === "speed_tie") return `同速 ${row.enemy_current_speed}`;
  if (row.relation === "self_faster") return `我方快 ${formatSigned(row.delta)}${closeText}`;
  if (row.relation === "enemy_faster") return `敌方快 ${formatSigned(row.delta)}${closeText}`;
  return `未知 ${row.enemy_current_speed}`;
}

function speedRelationClassName(row: SpeedPreviewRow) {
  if (row.relation === "self_faster") return "font-medium text-emerald-700";
  if (row.relation === "enemy_faster") return "font-medium text-rose-700";
  if (row.relation === "speed_tie") return "font-medium text-amber-700";
  return "font-medium text-slate-700";
}

function formatSigned(value: number) {
  if (!Number.isFinite(value)) return "--";
  return value > 0 ? `+${value}` : String(value);
}

function hasPanelStats(rawJson?: string | null): boolean {
  if (!rawJson) return false;
  try {
    const value = JSON.parse(rawJson) as Partial<StatBlock>;
    return (
      Number.isFinite(value.hp)
      && Number.isFinite(value.physical_attack)
      && Number.isFinite(value.physical_defense)
      && Number.isFinite(value.magic_attack)
      && Number.isFinite(value.magic_defense)
      && Number.isFinite(value.speed)
    );
  } catch {
    return false;
  }
}

function statBlockFromStatsJson(rawJson?: string | null): StatBlock | undefined {
  if (!rawJson) return undefined;
  try {
    return statBlockFromUnknown(JSON.parse(rawJson));
  } catch {
    return undefined;
  }
}

function statBlockFromUnknown(value: unknown): StatBlock | undefined {
  if (!value || typeof value !== "object") return undefined;
  const stats = value as Partial<StatBlock>;
  if (
    Number.isFinite(stats.hp)
    && Number.isFinite(stats.physical_attack)
    && Number.isFinite(stats.physical_defense)
    && Number.isFinite(stats.magic_attack)
    && Number.isFinite(stats.magic_defense)
    && Number.isFinite(stats.speed)
  ) {
    return {
      hp: Number(stats.hp),
      physical_attack: Number(stats.physical_attack),
      physical_defense: Number(stats.physical_defense),
      magic_attack: Number(stats.magic_attack),
      magic_defense: Number(stats.magic_defense),
      speed: Number(stats.speed),
    };
  }
  return undefined;
}

function natureSourceName(value: string) {
  const names: Record<string, string> = {
    matched_player_build: "己方配置",
    enemy_default_config: "敌方估计",
  };
  return names[value] ?? value;
}
