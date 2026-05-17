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

export function BattleWorkbenchPage() {
  const queryClient = useQueryClient();
  const { currentBattleId, openDrawer, setCandidatePanelElfId, candidatePanelElfId } = useAppStore();
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

  const finishBattle = useMutation({
    mutationFn: () => api.battles.finish(currentBattleId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["battle-state", currentBattleId] });
      queryClient.invalidateQueries({ queryKey: ["battles"] });
    },
  });

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
          <Badge variant="warning">manual only</Badge>
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
                <Button variant="ghost" onClick={() => stateQuery.refetch()}>刷新</Button>
              </CardContent>
            </Card>

            <Card>
              <CardHeader><CardTitle>统一状态系统</CardTitle></CardHeader>
              <CardContent><ActiveEffectsPanel battleId={currentBattleId!} effects={state.active_effects} /></CardContent>
            </Card>

            <EventTimeline battleId={currentBattleId} compact />
          </div>

          <div className="space-y-4">
            <CandidatePanel battleId={currentBattleId} elfId={candidateElfId} />
            <Card>
              <CardHeader><CardTitle>速度与伤害提示</CardTitle></CardHeader>
              <CardContent className="space-y-3 text-sm">
                <div className="rounded-2xl border bg-white p-3">真实先手概率：<span className="font-semibold text-amber-700">未实现</span></div>
                <div className="rounded-2xl border bg-white p-3">真实伤害区间：<span className="font-semibold text-amber-700">未实现</span></div>
                <div className="rounded-2xl border bg-white p-3">击杀判断：<span className="font-semibold text-amber-700">未实现</span></div>
              </CardContent>
            </Card>
          </div>
        </div>
      ) : null}

      <ManualEventDrawer battleId={currentBattleId} state={state ? { battle: state.battle, elves: state.elves } : undefined} />
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
