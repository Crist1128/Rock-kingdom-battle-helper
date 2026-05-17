import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Server } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Textarea } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { compactId, phaseName } from "@/lib/utils";
import { useAppStore } from "@/store/useAppStore";

export function DashboardPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [battleName, setBattleName] = useState(`PVP ${new Date().toLocaleDateString()}`);
  const [notes, setNotes] = useState("");
  const [manualBattleId, setManualBattleId] = useState("");
  const { currentBattleId, recentBattles, addRecentBattle, removeRecentBattle, setCurrentBattleId } = useAppStore();
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });
  const battlesQuery = useQuery({ queryKey: ["battles", "recent"], queryFn: () => api.battles.list({ limit: 50 }) });
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
      window.alert(`移除战斗失败：${message}`);
    },
  });

  const removeBattle = (battleId: string) => {
    if (!window.confirm("确认从最近战斗中移除？该操作会归档战斗，但不会删除历史事件和候选数据。")) {
      return;
    }
    if (battlesQuery.data) {
      archiveBattle.mutate(battleId);
      return;
    }
    removeRecentBattle(battleId);
    if (currentBattleId === battleId) {
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
            <CardTitle>最近战斗</CardTitle>
            <CardDescription>优先显示后端战斗列表；网络异常时仍可手动添加 battle_id。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <form className="flex gap-2" onSubmit={addManualBattle}>
              <Input value={manualBattleId} onChange={(e) => setManualBattleId(e.target.value)} placeholder="手动输入 battle_id" />
              <Button variant="outline" type="submit">添加</Button>
            </form>
            {(battlesQuery.data ?? recentBattles).length === 0 ? <div className="rounded-2xl border bg-slate-50 p-4 text-sm text-muted-foreground">暂无战斗记录。</div> : null}
            {battlesQuery.isError ? <div className="rounded-2xl border bg-amber-50 p-3 text-sm text-amber-900">后端战斗列表读取失败，已显示本地记录。</div> : null}
            {(battlesQuery.data ?? recentBattles).map((battle) => (
              <div key={battle.battle_id} className="flex items-center justify-between rounded-2xl border bg-white p-4">
                <div>
                  <div className="font-medium">{battle.battle_name ?? compactId(battle.battle_id)}</div>
                  <div className="mt-1 text-xs text-muted-foreground">{battle.battle_id}</div>
                  <div className="mt-2 flex gap-2"><Badge variant="outline">{phaseName(battle.phase)}</Badge><Badge variant="secondary">{battle.updated_at ? new Date(battle.updated_at).toLocaleString() : "暂无更新时间"}</Badge></div>
                </div>
                <div className="flex gap-2">
                  <Button onClick={() => openBattle(battle.battle_id)}>进入</Button>
                  <Button
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
        <QuickLink to="/rules" title="规则库" desc="只读查看精灵/技能/状态" />
      </div>
    </div>
  );
}

function QuickLink({ to, title, desc }: { to: string; title: string; desc: string }) {
  return (
    <Link to={to} className="rounded-2xl border bg-white p-4 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md">
      <div className="font-semibold">{title}</div>
      <div className="mt-1 text-sm text-muted-foreground">{desc}</div>
    </Link>
  );
}
