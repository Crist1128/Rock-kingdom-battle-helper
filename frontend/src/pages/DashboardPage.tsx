import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Server, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Textarea } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { compactId, cn, phaseName } from "@/lib/utils";
import { useConfirm } from "@/components/ui/confirm";
import { useToast } from "@/components/ui/toast";
import { useAppStore } from "@/store/useAppStore";

export function DashboardPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const { toast } = useToast();
  const [battleName, setBattleName] = useState(`PVP ${new Date().toLocaleDateString()}`);
  const [notes, setNotes] = useState("");
  const [manualBattleId, setManualBattleId] = useState("");
  const {
    currentBattleId,
    recentBattles,
    addRecentBattle,
    removeRecentBattle,
    clearRecentBattles,
    setCurrentBattleId,
  } = useAppStore();
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });
  const battlesQuery = useQuery({ queryKey: ["battles", "recent"], queryFn: () => api.battles.list({ limit: 50 }) });
  const displayedBattles = battlesQuery.data ?? recentBattles;
  const createBattle = useMutation({
    mutationFn: () => api.battles.create({ battle_name: battleName, notes }),
    onSuccess: (battle) => {
      addRecentBattle(battle);
      navigate("/preparation");
    },
  });

  const openBattle = (battleId: string) => {
    setCurrentBattleId(battleId);
    navigate("/battle");
  };

  const archiveBattle = useMutation({
    mutationFn: (battleId: string) => api.battles.archive(battleId),
    onSuccess: (archivedBattle) => {
      removeRecentBattle(archivedBattle.battle_id);
      if (currentBattleId === archivedBattle.battle_id) {
        setCurrentBattleId(null);
      }
      queryClient.setQueryData(["battles", "recent"], (old: unknown) => {
        if (!Array.isArray(old)) return old;
        return old.filter((item) => {
          if (typeof item !== "object" || item === null || !("battle_id" in item)) return true;
          return (item as { battle_id?: string }).battle_id !== archivedBattle.battle_id;
        });
      });
      queryClient.invalidateQueries({ queryKey: ["battles"] });
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : "归档失败";
      toast(`移除战斗失败：${message}`, "error");
    },
  });

  const archiveAllBattles = useMutation({
    mutationFn: async (battleIds: string[]) => {
      if (!battlesQuery.data) return [];
      return Promise.all(battleIds.map((battleId) => api.battles.archive(battleId)));
    },
    onSuccess: (_archived, battleIds) => {
      clearRecentBattles();
      if (currentBattleId && battleIds.includes(currentBattleId)) {
        setCurrentBattleId(null);
      }
      queryClient.setQueryData(["battles", "recent"], []);
      queryClient.invalidateQueries({ queryKey: ["battles"] });
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : "批量归档失败";
      toast(`批量移除战斗失败：${message}`, "error");
    },
  });

  const removeBattle = async (battleId: string) => {
    const confirmed = await confirm({
      title: "移除战斗",
      description: "该操作会归档战斗，但不会删除历史事件和实时估计数据。",
      confirmText: "移除",
    });
    if (!confirmed) return;
    if (battlesQuery.data) {
      archiveBattle.mutate(battleId);
      return;
    }
    removeRecentBattle(battleId);
    if (currentBattleId === battleId) {
      setCurrentBattleId(null);
    }
  };

  const removeAllBattles = async () => {
    if (displayedBattles.length === 0) return;
    const confirmed = await confirm({
      title: "移除全部最近战斗",
      description: "后端战斗会被归档，历史事件和实时估计数据仍会保留。",
      confirmText: "全部移除",
      danger: true,
    });
    if (!confirmed) return;
    const battleIds = displayedBattles.map((battle) => battle.battle_id);
    if (battlesQuery.data) {
      archiveAllBattles.mutate(battleIds);
      return;
    }
    clearRecentBattles();
    if (currentBattleId && battleIds.includes(currentBattleId)) {
      setCurrentBattleId(null);
    }
  };

  const addManualBattle = (event: FormEvent) => {
    event.preventDefault();
    if (!manualBattleId.trim()) return;
    const battle_id = manualBattleId.trim();
    addRecentBattle({ battle_id, battle_name: "手动添加的 battle_id", phase: null });
    setManualBattleId("");
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold">战斗首页</h1>
          <p className="mt-1 text-muted-foreground">创建战斗、进入准备阶段或打开最近战斗。优先读取后端战斗列表，本地记录仅作为补充。</p>
        </div>
        <Badge variant={health.data?.status === "ok" ? "success" : health.isError ? "destructive" : "secondary"}>
          <Server className="mr-1 h-3 w-3" /> 后端 {health.data?.status ?? (health.isLoading ? "检测中" : "异常")}
        </Badge>
      </div>

      <div className="grid grid-cols-[420px_1fr] gap-6">
        <Card>
          <CardHeader>
            <CardTitle>新建战斗</CardTitle>
            <CardDescription>创建后进入准备阶段录入双方阵容。</CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); createBattle.mutate(); }}>
              <div>
                <label className="text-sm font-medium">战斗名称</label>
                <Input value={battleName} onChange={(e) => setBattleName(e.target.value)} />
              </div>
              <div>
                <label className="text-sm font-medium">备注</label>
                <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="可记录对手、日期、测试目的" />
              </div>
              <Button className="w-full" type="submit" disabled={createBattle.isPending}>
                <Plus className="h-4 w-4" /> {createBattle.isPending ? "创建中..." : "创建战斗"}
              </Button>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-start justify-between gap-3">
              <div>
                <CardTitle>最近战斗</CardTitle>
                <CardDescription>优先显示后端战斗列表；网络异常时仍可手动添加 battle_id。</CardDescription>
              </div>
              <Button
                variant="outline"
                size="sm"
                disabled={displayedBattles.length === 0 || archiveAllBattles.isPending}
                onClick={removeAllBattles}
              >
                <Trash2 className="h-4 w-4" />
                {archiveAllBattles.isPending ? "移除中..." : "全部移除"}
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            <form className="flex gap-2" onSubmit={addManualBattle}>
              <Input value={manualBattleId} onChange={(e) => setManualBattleId(e.target.value)} placeholder="手动输入 battle_id" />
              <Button variant="outline" type="submit">添加</Button>
            </form>
            {displayedBattles.length === 0 ? <div className="rounded-2xl border bg-raised/60 p-4 text-sm text-muted-foreground">暂无战斗记录。</div> : null}
            {battlesQuery.isError ? <div className="rounded-2xl border bg-warning/10 p-3 text-sm text-warning">后端战斗列表读取失败，已显示本地记录。</div> : null}
            {displayedBattles.map((battle) => (
              <div
                key={battle.battle_id}
                className="group flex items-center gap-3 rounded-lg border border-transparent bg-raised/40 px-3 py-2.5 transition-colors hover:border-border hover:bg-raised"
              >
                <span
                  className={cn(
                    "h-1.5 w-1.5 shrink-0 rounded-full",
                    battle.phase === "battle"
                      ? "bg-success shadow-glow-sm"
                      : battle.phase === "preparation"
                        ? "bg-warning"
                        : "bg-muted-foreground/50",
                  )}
                />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{battle.battle_name ?? compactId(battle.battle_id)}</div>
                  <div className="font-num mt-0.5 truncate text-[11px] text-muted-foreground">
                    {compactId(battle.battle_id)}
                    {battle.updated_at ? ` · ${new Date(battle.updated_at).toLocaleString()}` : ""}
                  </div>
                </div>
                <Badge variant="outline" className="shrink-0">{phaseName(battle.phase)}</Badge>
                <div className="flex shrink-0 gap-1.5">
                  <Button size="sm" onClick={() => openBattle(battle.battle_id)}>进入</Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={archiveBattle.isPending}
                    onClick={() => removeBattle(battle.battle_id)}
                  >
                    移除
                  </Button>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-4 gap-4">
        <QuickLink to="/builds" title="己方配置" desc="录入确定面板与技能组" />
        <QuickLink to="/preparation" title="准备阶段" desc="录入双方 6 只精灵" />
        <QuickLink to="/battle" title="战斗工作台" desc="快速手动录入事件" />
        <QuickLink to="/rules" title="规则库" desc="查看规则并维护技能效果" />
      </div>
    </div>
  );
}

function QuickLink({ to, title, desc }: { to: string; title: string; desc: string }) {
  return (
    <Link to={to} className="rounded-2xl border bg-raised/60 p-4 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md">
      <div className="font-semibold">{title}</div>
      <div className="mt-1 text-sm text-muted-foreground">{desc}</div>
    </Link>
  );
}
