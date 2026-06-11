import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAppStore } from "@/store/useAppStore";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Select } from "@/components/ui/select";
import { SkillSearchSelect } from "@/components/EntitySearchSelect";
import { ElfCard } from "@/components/ElfCard";
import { StatGrid } from "@/components/StatGrid";
import { EstimatePanel, type EstimatePanelSelection } from "@/components/EstimatePanel";
import { EventTimeline } from "@/components/EventTimeline";
import { ActiveEffectsPanel } from "@/components/ActiveEffectsPanel";
import { ManualEventDrawer } from "@/components/ManualEventDrawer";
import { phaseName, sideName } from "@/lib/utils";
import type { BattleElfStateDict, BattleEventOut, DamageEventCreateResult, EndTurnResult, Side, SkillDefinitionOut, StatBlock } from "@/types/api";

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
        <div className="grid grid-cols-[280px_1fr_360px] gap-6">
          <div className="space-y-4">
            <TeamPanel title="我方队伍" elves={selfElves} activeElfId={state.battle.self_active_elf_id} onSwitch={() => { setEstimatePanelElfId(null); openDrawer("switch", "self"); }} />
            <TeamPanel title="敌方队伍" elves={enemyElves} activeElfId={state.battle.enemy_active_elf_id} onSwitch={() => openDrawer("switch", "enemy")} onSelectEstimate={setEstimatePanelElfId} />
          </div>

          <div className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle>当前对位</CardTitle>
              </CardHeader>
              <CardContent className="grid grid-cols-2 gap-4">
                <ActiveSide title="我方上场" elf={selfActive} />
                <ActiveSide
                  title="敌方上场"
                  elf={enemyActive}
                  estimatedStats={enemyEstimatedStats}
                  estimateSource={activeEnemyEstimate?.source ?? "unknown"}
                  estimateMatchedCount={activeEnemyEstimate?.matchedCount ?? 0}
                  estimateNatureName={activeEnemyEstimate?.natureName}
                />
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

            {lastEndTurnResult ? <EndTurnSummary result={lastEndTurnResult} /> : null}
            {lastSkillEvent ? <SkillOperationSummary event={lastSkillEvent} /> : null}
            {lastDamageEventResult ? <DamageEventSummary result={lastDamageEventResult} /> : null}

            <Card>
              <CardHeader><CardTitle>统一状态系统</CardTitle></CardHeader>
              <CardContent><ActiveEffectsPanel battleId={currentBattleId!} effects={state.active_effects} /></CardContent>
            </Card>

            <EventTimeline battleId={currentBattleId} compact />
          </div>

          <div className="space-y-4">
            <EstimatePanel
              battleId={currentBattleId}
              elfId={estimateElfId}
              onEstimateChange={setEnemyEstimateSelection}
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
          <div className="text-xs text-muted-foreground">{activeElf?.elf_name ?? activeElfId ?? "未选择上场精灵"}</div>
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

function formatOptionalBool(value: unknown) {
  if (value === true) return "成功";
  if (value === false) return "失败";
  return "未指定";
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

function TeamPanel({ title, elves, activeElfId, onSwitch, onSelectEstimate }: { title: string; elves: Array<any>; activeElfId?: string | null; onSwitch: (elfId: string) => void; onSelectEstimate?: (elfId: string) => void }) {
  return (
    <Card>
      <CardHeader><CardTitle>{title}</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        {elves.map((elf) => <ElfCard key={elf.elf_id} elf={elf} active={elf.elf_id === activeElfId} onSwitch={() => onSwitch(elf.elf_id)} onSelectEstimate={onSelectEstimate ? () => onSelectEstimate(elf.elf_id) : undefined} />)}
      </CardContent>
    </Card>
  );
}

function ActiveSide({
  title,
  elf,
  estimatedStats,
  estimateSource = "unknown",
  estimateMatchedCount = 0,
  estimateNatureName,
}: {
  title: string;
  elf?: any;
  estimatedStats?: StatBlock | null;
  estimateSource?: "default_config" | "expanded_config" | "base_talent" | "unknown";
  estimateMatchedCount?: number;
  estimateNatureName?: string | null;
}) {
  const hasRuntimeStats = hasPanelStats(elf?.panel_stats_json);
  return (
    <div className="rounded-2xl border bg-white p-4">
      <div className="mb-2 flex items-center justify-between"><div className="font-semibold">{title}</div><Badge variant="outline">{sideName(elf?.side)}</Badge></div>
      {elf ? (
        <div className="space-y-3">
          <div className="text-lg font-semibold">{elf.elf_name ?? elf.elf_id}</div>
          <div className="text-sm text-muted-foreground">HP {elf.current_hp_percent ?? "--"}% · 能量 {elf.energy ?? 0}</div>
          {!hasRuntimeStats && estimateNatureName ? (
            <div className="rounded-xl border bg-slate-50 p-2 text-xs text-muted-foreground">
              当前选择性格：<span className="font-medium text-slate-900">{estimateNatureName}</span>
            </div>
          ) : null}
          <StatGrid statsJson={hasRuntimeStats ? elf.panel_stats_json : undefined} stats={!hasRuntimeStats ? estimatedStats : undefined} />
          {!hasRuntimeStats && estimatedStats ? (
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
          {!hasRuntimeStats && !estimatedStats ? (
            <div className="text-xs text-muted-foreground">敌方真实六维未知，设置默认配置后可显示估计面板；后端会按当前推导约束校验保存。</div>
          ) : null}
        </div>
      ) : <div className="text-sm text-muted-foreground">未选择上场精灵。</div>}
    </div>
  );
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
