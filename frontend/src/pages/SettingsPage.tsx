import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { API_BASE_URL, ApiError, api } from "@/lib/api";
import type { BattleOut, BattlePurgeResultOut } from "@/types/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function SettingsPage() {
  const queryClient = useQueryClient();
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });
  const archivedBattles = useQuery({
    queryKey: ["battles", "archived"],
    queryFn: () => api.battles.list({ phase: "archived", limit: 100 }),
  });

  const [adminToken, setAdminToken] = useState(() => localStorage.getItem("adminToken") ?? "");
  const [olderThanDays, setOlderThanDays] = useState("");
  const [bulkLimit, setBulkLimit] = useState("50");
  const [lastResult, setLastResult] = useState<BattlePurgeResultOut | null>(null);
  const [singleResults, setSingleResults] = useState<Record<string, BattlePurgeResultOut>>({});

  useEffect(() => {
    if (adminToken) localStorage.setItem("adminToken", adminToken);
    else localStorage.removeItem("adminToken");
  }, [adminToken]);

  const refreshBattleLists = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["battles"] }),
      queryClient.invalidateQueries({ queryKey: ["battles", "archived"] }),
    ]);
  };

  const bulkPurgeMutation = useMutation({
    mutationFn: (dryRun: boolean) =>
      api.adminBattles.purgeArchived(
        {
          dry_run: dryRun,
          older_than_days: toNullableNumber(olderThanDays),
          limit: toNullableNumber(bulkLimit),
        },
        adminToken || undefined,
      ),
    onSuccess: async (result) => {
      setLastResult(result);
      if (!result.dry_run) await refreshBattleLists();
    },
  });

  const singlePurgeMutation = useMutation({
    mutationFn: async ({ battleId, dryRun }: { battleId: string; dryRun: boolean }) => {
      // 真正物理删除前先请求 purge-plan。这样可以提前确认后端路由已注册、
      // 战斗仍然存在且处于可删除状态；否则直接 DELETE 只会得到笼统的 404/400。
      if (!dryRun) {
        const plan = await api.adminBattles.purgePlan(battleId, adminToken || undefined);
        if (!plan.can_purge) {
          throw new Error(plan.reason || "当前战斗不允许物理删除，请先归档后再清理。");
        }
      }
      return api.adminBattles.purgeBattle(battleId, { dry_run: dryRun }, adminToken || undefined);
    },
    onSuccess: async (result) => {
      setSingleResults((old) => ({ ...old, [result.battle_ids[0] ?? "unknown"]: result }));
      if (!result.dry_run) await refreshBattleLists();
    },
    onError: async (error) => {
      // 如果后端返回 battle_not_found，通常说明列表里的战斗已经被批量清理或当前页面数据过期。
      // 自动刷新归档列表，避免用户继续对 stale item 操作。
      if (error instanceof ApiError && error.status === 404) {
        await archivedBattles.refetch();
      }
    },
  });

  const bulkError = getApiErrorText(bulkPurgeMutation.error);
  const singleError = getApiErrorText(singlePurgeMutation.error);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">设置 / 数据管理</h1>
        <p className="mt-1 text-muted-foreground">连接状态、静态数据说明与归档战斗清理。</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>后端连接</CardTitle>
          <CardDescription>
            默认通过 Vite 代理访问 `/api/v1`，也可用 `.env` 的 `VITE_API_BASE_URL` 指向完整后端地址。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="rounded-2xl border bg-white p-4">
            <div className="text-sm text-muted-foreground">API Base URL</div>
            <div className="mt-1 font-mono text-sm">{API_BASE_URL}</div>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={health.data?.status === "ok" ? "success" : health.isError ? "destructive" : "secondary"}>
              health: {health.data?.status ?? "unknown"}
            </Badge>
            <Button variant="outline" size="sm" onClick={() => health.refetch()}>重新检测</Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>归档战斗物理清理</CardTitle>
          <CardDescription>
            “移除最近战斗”只是归档；这里会真正删除归档战斗及其候选、事件、快照、状态实例和计算缓存。
            默认先 dry-run 预览，确认无误后再执行删除。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="grid grid-cols-3 gap-3">
            <label className="space-y-1">
              <span className="text-sm font-medium">Admin Token</span>
              <Input
                type="password"
                value={adminToken}
                placeholder="后端未配置 ADMIN_UPDATE_TOKEN 时可留空"
                onChange={(event) => setAdminToken(event.target.value)}
              />
            </label>
            <label className="space-y-1">
              <span className="text-sm font-medium">只清理 N 天前归档</span>
              <Input
                value={olderThanDays}
                placeholder="留空 = 不按时间过滤"
                onChange={(event) => setOlderThanDays(event.target.value.replace(/[^0-9]/g, ""))}
              />
            </label>
            <label className="space-y-1">
              <span className="text-sm font-medium">批量上限</span>
              <Input
                value={bulkLimit}
                placeholder="默认 50，留空 = 不限制"
                onChange={(event) => setBulkLimit(event.target.value.replace(/[^0-9]/g, ""))}
              />
            </label>
          </div>

          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              onClick={() => bulkPurgeMutation.mutate(true)}
              disabled={bulkPurgeMutation.isPending}
            >
              预览批量清理
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                if (window.confirm("确认物理删除符合条件的归档战斗？此操作不可恢复。")) {
                  bulkPurgeMutation.mutate(false);
                }
              }}
              disabled={bulkPurgeMutation.isPending}
            >
              执行批量删除
            </Button>
            <Button variant="ghost" onClick={() => archivedBattles.refetch()}>刷新归档列表</Button>
          </div>

          {bulkError ? <ErrorBox text={bulkError} /> : null}
          {lastResult ? <PurgeResultPanel title="批量清理结果" result={lastResult} /> : null}

          <div className="rounded-2xl border bg-white p-4">
            <div className="mb-3 flex items-center justify-between">
              <div>
                <div className="font-semibold">已归档战斗</div>
                <div className="text-sm text-muted-foreground">只列出 phase = archived 的战斗。</div>
              </div>
              <Badge variant="outline">{archivedBattles.data?.length ?? 0} 场</Badge>
            </div>
            <div className="space-y-2">
              {archivedBattles.isLoading ? <div className="text-sm text-muted-foreground">正在加载归档战斗...</div> : null}
              {archivedBattles.data?.length === 0 ? <div className="text-sm text-muted-foreground">暂无归档战斗。</div> : null}
              {archivedBattles.data?.map((battle) => (
                <ArchivedBattleRow
                  key={battle.battle_id}
                  battle={battle}
                  result={singleResults[battle.battle_id]}
                  pending={singlePurgeMutation.isPending}
                  onPreview={() => singlePurgeMutation.mutate({ battleId: battle.battle_id, dryRun: true })}
                  onDelete={() => {
                    if (window.confirm(`确认物理删除「${battle.battle_name ?? battle.battle_id}」？此操作不可恢复。`)) {
                      singlePurgeMutation.mutate({ battleId: battle.battle_id, dryRun: false });
                    }
                  }}
                />
              ))}
            </div>
            {singleError ? <ErrorBox text={singleError} /> : null}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>BWIKI 静态数据</CardTitle>
          <CardDescription>前端只读取普通业务接口，不直接读取爬虫 raw/cleaned 文件。</CardDescription>
        </CardHeader>
        <CardContent className="grid grid-cols-3 gap-3">
          <InfoBox title="精灵" desc="GET /api/v1/elves，解析 element_types_json，使用 avatar 远程 URL。" />
          <InfoBox title="技能" desc="GET /api/v1/skills，伤害规则仍以 formula_unavailable 占位展示。" />
          <InfoBox title="管理更新" desc="/admin/data-updates 仍由管理令牌保护，建议只在需要更新规则数据时主动触发。" />
        </CardContent>
      </Card>
    </div>
  );
}

function ArchivedBattleRow({
  battle,
  result,
  pending,
  onPreview,
  onDelete,
}: {
  battle: BattleOut;
  result?: BattlePurgeResultOut;
  pending: boolean;
  onPreview: () => void;
  onDelete: () => void;
}) {
  return (
    <div className="rounded-xl border bg-slate-50 p-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="font-medium">{battle.battle_name || battle.battle_id}</div>
          <div className="mt-1 text-xs text-muted-foreground">
            {battle.battle_id} · 更新时间：{battle.updated_at ? new Date(battle.updated_at).toLocaleString() : "未知"}
          </div>
        </div>
        <div className="flex shrink-0 gap-2">
          <Button variant="outline" size="sm" disabled={pending} onClick={onPreview}>预览</Button>
          <Button variant="destructive" size="sm" disabled={pending} onClick={onDelete}>物理删除</Button>
        </div>
      </div>
      {result ? <PurgeResultPanel title="单场预览/清理结果" result={result} compact /> : null}
    </div>
  );
}

function PurgeResultPanel({ title, result, compact = false }: { title: string; result: BattlePurgeResultOut; compact?: boolean }) {
  return (
    <div className={compact ? "mt-3 rounded-xl border bg-white p-3" : "rounded-2xl border bg-white p-4"}>
      <div className="flex items-center justify-between gap-3">
        <div className="font-semibold">{title}</div>
        <Badge variant={result.dry_run ? "secondary" : "destructive"}>{result.dry_run ? "dry-run" : "已删除"}</Badge>
      </div>
      <div className="mt-2 text-sm text-muted-foreground">{result.message}</div>
      <div className="mt-3 grid grid-cols-2 gap-2 text-sm md:grid-cols-4">
        <InfoMini label="战斗数" value={String(result.battle_count)} />
        <InfoMini label="候选" value={String(result.rows.build_candidate ?? 0)} />
        <InfoMini label="事件" value={String(result.rows.battle_event ?? 0)} />
        <InfoMini label="快照" value={String(result.rows.battle_effect_snapshot ?? 0)} />
      </div>
      <details className="mt-3">
        <summary className="cursor-pointer text-sm text-muted-foreground">查看各表行数</summary>
        <pre className="mt-2 overflow-auto rounded-xl bg-slate-950 p-3 text-xs text-white">{JSON.stringify(result.rows, null, 2)}</pre>
      </details>
    </div>
  );
}

function InfoMini({ label, value }: { label: string; value: string }) {
  return <div className="rounded-xl bg-slate-100 p-2"><div className="text-xs text-muted-foreground">{label}</div><div className="font-mono font-semibold">{value}</div></div>;
}

function InfoBox({ title, desc }: { title: string; desc: string }) {
  return <div className="rounded-2xl border bg-white p-4"><div className="font-semibold">{title}</div><div className="mt-1 text-sm text-muted-foreground">{desc}</div></div>;
}

function ErrorBox({ text }: { text: string }) {
  return <div className="rounded-2xl border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">{text}</div>;
}

function toNullableNumber(value: string): number | null {
  if (!value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function getApiErrorText(error: unknown): string | null {
  if (!error) return null;
  if (error instanceof ApiError) {
    if (typeof error.detail === "string") return error.detail;
    if (error.detail && typeof error.detail === "object" && "detail" in error.detail) {
      const detail = (error.detail as { detail?: unknown }).detail;
      if (typeof detail === "string") return detail;
      if (detail && typeof detail === "object") {
        const data = detail as { message?: unknown; hint?: unknown; code?: unknown };
        const message = typeof data.message === "string" ? data.message : JSON.stringify(detail);
        const hint = typeof data.hint === "string" ? `\n${data.hint}` : "";
        return `${message}${hint}`;
      }
      return JSON.stringify(detail);
    }
    return error.message;
  }
  return error instanceof Error ? error.message : String(error);
}
