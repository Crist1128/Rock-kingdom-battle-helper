import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAppStore } from "@/store/useAppStore";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ElfCard } from "@/components/ElfCard";
import { StatGrid } from "@/components/StatGrid";
import { EstimatePanel, type EstimatePanelSelection } from "@/components/EstimatePanel";
import { EventTimeline } from "@/components/EventTimeline";
import { ActiveEffectsPanel } from "@/components/ActiveEffectsPanel";
import { ManualEventDrawer } from "@/components/ManualEventDrawer";
import { phaseName, sideName } from "@/lib/utils";
import type { EndTurnResult, StatBlock } from "@/types/api";

export function BattleWorkbenchPage() {
  const queryClient = useQueryClient();
  const { currentBattleId, openDrawer, setEstimatePanelElfId, estimatePanelElfId } = useAppStore();
  const [lastEndTurnResult, setLastEndTurnResult] = useState<EndTurnResult | null>(null);
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

            <Card>
              <CardHeader>
                <CardTitle>快捷录入</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="grid grid-cols-4 gap-2">
                  <Button onClick={() => openDrawer("skill", "self")}>我方用技能</Button>
                  <Button variant="outline" onClick={() => openDrawer("skill", "enemy")}>敌方用技能</Button>
                  <Button variant="outline" onClick={() => openDrawer("damage", "self")}>造成伤害</Button>
                  <Button variant="outline" onClick={() => openDrawer("damage", "enemy")}>受到伤害</Button>
                </div>
                <div className="grid grid-cols-4 gap-2">
                  <Button variant="outline" onClick={() => openDrawer("resource", "self")}>治疗/能量</Button>
                  <Button variant="outline" onClick={() => openDrawer("effect", "self")}>我方状态</Button>
                  <Button variant="outline" onClick={() => openDrawer("effect", "enemy")}>敌方状态</Button>
                  <Button variant="secondary" disabled={!canEndTurn || endTurn.isPending} onClick={requestEndTurn}>
                    {endTurn.isPending ? "结算中..." : "结束回合"}
                  </Button>
                </div>
                <div className="grid grid-cols-3 gap-2">
                  <Button variant="outline" onClick={() => openDrawer("switch", "self")}>我方切换</Button>
                  <Button variant="outline" onClick={() => openDrawer("switch", "enemy")}>敌方切换</Button>
                  <Button variant="ghost" onClick={() => stateQuery.refetch()}>刷新</Button>
                </div>
              </CardContent>
            </Card>

            {lastEndTurnResult ? <EndTurnSummary result={lastEndTurnResult} /> : null}

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
                <Capability label="旧候选空间" value="已下线" muted />
              </CardContent>
            </Card>
          </div>
        </div>
      ) : null}

      <ManualEventDrawer battleId={currentBattleId} state={state ? { battle: state.battle, elves: state.elves } : undefined} />
    </div>
  );
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
                ? `显示你选择的实时展开配置，命中 ${estimateMatchedCount} 项约束。`
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
