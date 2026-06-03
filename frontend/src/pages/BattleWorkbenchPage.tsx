import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAppStore } from "@/store/useAppStore";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ElfCard } from "@/components/ElfCard";
import { StatGrid } from "@/components/StatGrid";
import { CandidatePanel } from "@/components/CandidatePanel";
import { EventTimeline } from "@/components/EventTimeline";
import { ActiveEffectsPanel } from "@/components/ActiveEffectsPanel";
import { ManualEventDrawer } from "@/components/ManualEventDrawer";
import { phaseName, sideName } from "@/lib/utils";
import type { EndTurnResult } from "@/types/api";

export function BattleWorkbenchPage() {
  const queryClient = useQueryClient();
  const { currentBattleId, openDrawer, setCandidatePanelElfId, candidatePanelElfId } = useAppStore();
  const [lastEndTurnResult, setLastEndTurnResult] = useState<EndTurnResult | null>(null);
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
  const candidateElfId = candidatePanelElfId ?? state?.battle.enemy_active_elf_id;
  const canEndTurn = Boolean(currentBattleId && state && state.battle.phase === "battle");

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
      queryClient.invalidateQueries({ queryKey: ["candidate-summary"] });
      queryClient.invalidateQueries({ queryKey: ["candidate-detail"] });
      queryClient.invalidateQueries({ queryKey: ["candidate-list"] });
      queryClient.invalidateQueries({ queryKey: ["candidate-evidence"] });
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
    if (!window.confirm("确认结束当前战斗？结束后仍可查看事件和候选记录。")) return;
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
          <Badge variant="success">soft scoring</Badge>
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
            <TeamPanel title="我方队伍" elves={selfElves} activeElfId={state.battle.self_active_elf_id} onSwitch={(elfId) => { setCandidatePanelElfId(null); openDrawer("switch", "self"); }} />
            <TeamPanel title="敌方队伍" elves={enemyElves} activeElfId={state.battle.enemy_active_elf_id} onSwitch={() => openDrawer("switch", "enemy")} onSelectCandidate={setCandidatePanelElfId} />
          </div>

          <div className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle>当前对位</CardTitle>
              </CardHeader>
              <CardContent className="grid grid-cols-2 gap-4">
                <ActiveSide title="我方上场" elf={selfActive} />
                <ActiveSide title="敌方上场" elf={enemyActive} />
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>快捷录入</CardTitle>
              </CardHeader>
              <CardContent className="grid grid-cols-4 gap-2">
                <Button onClick={() => openDrawer("damage", "self")}>造成伤害</Button>
                <Button variant="outline" onClick={() => openDrawer("damage", "enemy")}>受到伤害</Button>
                <Button variant="outline" onClick={() => openDrawer("resource", "self")}>治疗/能量</Button>
                <Button variant="outline" onClick={() => openDrawer("effect", "self")}>添加状态</Button>
                <Button variant="outline" onClick={() => openDrawer("effect", "enemy")}>敌方状态</Button>
                <Button variant="outline" onClick={() => openDrawer("switch", "self")}>我方切换</Button>
                <Button variant="outline" onClick={() => openDrawer("switch", "enemy")}>敌方切换</Button>
                <Button variant="secondary" disabled={!canEndTurn || endTurn.isPending} onClick={requestEndTurn}>
                  {endTurn.isPending ? "结算中..." : "结束回合"}
                </Button>
                <Button variant="ghost" onClick={() => stateQuery.refetch()}>刷新</Button>
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
            <CandidatePanel battleId={currentBattleId} elfId={candidateElfId} />
            <Card>
              <CardHeader><CardTitle>测试能力</CardTitle></CardHeader>
              <CardContent className="space-y-3 text-sm">
                <Capability label="普通攻击" value="最小公式可测" />
                <Capability label="状态/星陨" value="自动结算可测" />
                <Capability label="应对/防御" value="减伤上下文可测" />
                <Capability label="候选推理" value="软评分与 evidence" />
                <Capability label="硬排除" value="默认关闭" muted />
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
          候选反馈：匹配 {String(observationResult.matched_count ?? "--")}，冲突{" "}
          {String(observationResult.mismatched_count ?? "--")}，未知 {String(observationResult.unknown_count ?? "--")}
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

function TeamPanel({ title, elves, activeElfId, onSwitch, onSelectCandidate }: { title: string; elves: Array<any>; activeElfId?: string | null; onSwitch: (elfId: string) => void; onSelectCandidate?: (elfId: string) => void }) {
  return (
    <Card>
      <CardHeader><CardTitle>{title}</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        {elves.map((elf) => <ElfCard key={elf.elf_id} elf={elf} active={elf.elf_id === activeElfId} onSwitch={() => onSwitch(elf.elf_id)} onSelectCandidate={onSelectCandidate ? () => onSelectCandidate(elf.elf_id) : undefined} />)}
      </CardContent>
    </Card>
  );
}

function ActiveSide({ title, elf }: { title: string; elf?: any }) {
  return (
    <div className="rounded-2xl border bg-white p-4">
      <div className="mb-2 flex items-center justify-between"><div className="font-semibold">{title}</div><Badge variant="outline">{sideName(elf?.side)}</Badge></div>
      {elf ? (
        <div className="space-y-3">
          <div className="text-lg font-semibold">{elf.elf_name ?? elf.elf_id}</div>
          <div className="text-sm text-muted-foreground">HP {elf.current_hp_percent ?? "--"}% · 能量 {elf.energy ?? 0}</div>
          <StatGrid statsJson={elf.panel_stats_json} />
        </div>
      ) : <div className="text-sm text-muted-foreground">未选择上场精灵。</div>}
    </div>
  );
}
