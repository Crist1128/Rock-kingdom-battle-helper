import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { API_BASE_URL, ApiError, api } from "@/lib/api";
import type {
  BattleOut,
  BattlePurgeResultOut,
  ProjectDataBootstrapStatus,
  RocomCheckResponse,
  RocomDataUpdateAccepted,
  RocomDataUpdateJobStatus,
  RocomJobProgress,
  StaticSkillRuleSyncResponse,
} from "@/types/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/**
 * 设置 / 数据管理页面。
 *
 * 这里集中放置会影响本地数据库的“管理动作”：
 * 1. 规则数据更新：主动检查、远程同步、本地 cleaned JSON 导入。
 * 2. 归档战斗清理：dry-run 预览后再物理删除。
 *
 * 注意：数据更新不是后端启动流程的一部分，也不是常驻爬虫服务。
 * 普通使用只需要启动 backend + frontend；只有本地规则库为空或需要更新时，
 * 才在本页主动触发数据更新接口。
 */
export function SettingsPage() {
  const queryClient = useQueryClient();
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });
  const archivedBattles = useQuery({
    queryKey: ["battles", "archived"],
    queryFn: () => api.battles.list({ phase: "archived", limit: 100 }),
  });

  const [adminToken, setAdminToken] = useState(() => localStorage.getItem("adminToken") ?? "");

  // 静态数据更新表单状态。
  const [checkLimit, setCheckLimit] = useState("0");
  const [checkPreviewLimit, setCheckPreviewLimit] = useState("50");
  const [syncLimit, setSyncLimit] = useState("0");
  const [syncDelay, setSyncDelay] = useState("1.5");
  const [syncDataVersion, setSyncDataVersion] = useState("");
  const [syncForce, setSyncForce] = useState(false);
  const [syncWithImages, setSyncWithImages] = useState(false);
  const [syncWriteArtifacts, setSyncWriteArtifacts] = useState(true);
  const [syncUpdateMode, setSyncUpdateMode] = useState<"full" | "new_only">("full");
  const [localCleanedDir, setLocalCleanedDir] = useState("");
  const [localDataVersion, setLocalDataVersion] = useState("");
  const [localUpdateMode, setLocalUpdateMode] = useState<"full" | "incremental">("full");
  const [bootstrapCleanedDir, setBootstrapCleanedDir] = useState("");
  const [bootstrapDataVersion, setBootstrapDataVersion] = useState("");
  const [lastCheckResult, setLastCheckResult] = useState<RocomCheckResponse | null>(null);
  const [lastAcceptedJob, setLastAcceptedJob] = useState<RocomDataUpdateAccepted | null>(null);
  const [staticRuleCheckLimit, setStaticRuleCheckLimit] = useState("100");
  const [staticRuleSearch, setStaticRuleSearch] = useState("");
  const [lastStaticRuleResult, setLastStaticRuleResult] =
    useState<StaticSkillRuleSyncResponse | null>(null);
  const [selectedStaticRuleSkillIds, setSelectedStaticRuleSkillIds] = useState<string[]>([]);

  // 归档战斗清理表单状态。
  const [olderThanDays, setOlderThanDays] = useState("");
  const [bulkLimit, setBulkLimit] = useState("50");
  const [lastPurgeResult, setLastPurgeResult] = useState<BattlePurgeResultOut | null>(null);
  const [singleResults, setSingleResults] = useState<Record<string, BattlePurgeResultOut>>({});

  useEffect(() => {
    if (adminToken) localStorage.setItem("adminToken", adminToken);
    else localStorage.removeItem("adminToken");
  }, [adminToken]);

  const dataUpdateJobs = useQuery({
    queryKey: ["data-updates", "rocom", "jobs", Boolean(adminToken)],
    queryFn: () => api.adminDataUpdates.listRocomJobs(adminToken || undefined),
    refetchInterval: (query) => {
      const jobs = query.state.data as RocomDataUpdateJobStatus[] | undefined;
      return jobs?.some((job) => job.status === "queued" || job.status === "running") ? 1000 : false;
    },
  });

  const bootstrapStatus = useQuery({
    queryKey: ["data-updates", "bootstrap", "status", bootstrapCleanedDir, Boolean(adminToken)],
    queryFn: () =>
      api.adminDataUpdates.bootstrapStatus(
        { cleaned_dir: emptyToNull(bootstrapCleanedDir) },
        adminToken || undefined,
      ),
  });

  const runningJob = useMemo(
    () => dataUpdateJobs.data?.find((job) => job.status === "queued" || job.status === "running"),
    [dataUpdateJobs.data],
  );

  const refreshBattleLists = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["battles"] }),
      queryClient.invalidateQueries({ queryKey: ["battles", "archived"] }),
    ]);
  };

  const refreshRuleQueries = async () => {
    // 数据更新成功后，刷新所有依赖静态规则的前端缓存。
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["elves"] }),
      queryClient.invalidateQueries({ queryKey: ["skills"] }),
      queryClient.invalidateQueries({ queryKey: ["effects"] }),
      queryClient.invalidateQueries({ queryKey: ["natures"] }),
      queryClient.invalidateQueries({ queryKey: ["player-builds"] }),
      queryClient.invalidateQueries({ queryKey: ["data-updates", "rocom", "jobs"] }),
      queryClient.invalidateQueries({ queryKey: ["data-updates", "bootstrap"] }),
    ]);
  };

  const checkMutation = useMutation({
    mutationFn: () =>
      api.adminDataUpdates.checkRocom(
        {
          limit: toNumber(checkLimit, 0),
          include_new_elves_limit: toNumber(checkPreviewLimit, 50),
        },
        adminToken || undefined,
      ),
    onSuccess: (result) => setLastCheckResult(result),
  });

  const syncMutation = useMutation({
    mutationFn: async (commit: boolean) => {
      const check = await api.adminDataUpdates.checkRocom(
        {
          limit: 0,
          include_new_elves_limit: 50,
        },
        adminToken || undefined,
      );
      setLastCheckResult(check);
      if (syncUpdateMode === "new_only" && check.new_elf_count === 0) {
        throw new Error("远程检查没有发现新增精灵，已取消“只更新新增”任务。");
      }
      return api.adminDataUpdates.syncRocom(
        {
          commit,
          force: syncForce,
          limit: toNumber(syncLimit, 0),
          delay: toNumber(syncDelay, 1.5),
          with_images: syncWithImages,
          data_version: emptyToNull(syncDataVersion),
          write_artifacts: syncWriteArtifacts,
          refresh_static: syncUpdateMode === "full",
          update_mode: syncUpdateMode,
        },
        adminToken || undefined,
      );
    },
    onSuccess: async (result) => {
      setLastAcceptedJob(result);
      await refreshRuleQueries();
    },
  });

  const bootstrapLocalMutation = useMutation({
    mutationFn: (commit: boolean) =>
      api.adminDataUpdates.bootstrapImportLocal(
        {
          cleaned_dir: emptyToNull(bootstrapCleanedDir),
          commit,
          data_version: emptyToNull(bootstrapDataVersion),
        },
        adminToken || undefined,
      ),
    onSuccess: async (result) => {
      setLastAcceptedJob(result);
      await refreshRuleQueries();
    },
  });

  const importLocalMutation = useMutation({
    mutationFn: (commit: boolean) =>
      api.adminDataUpdates.importLocalRocom(
        {
          cleaned_dir: emptyToNull(localCleanedDir),
          commit,
          data_version: emptyToNull(localDataVersion),
          refresh_static: localUpdateMode === "full",
          update_mode: localUpdateMode,
        },
        adminToken || undefined,
      ),
    onSuccess: async (result) => {
      setLastAcceptedJob(result);
      await refreshRuleQueries();
    },
  });

  const staticRuleCheckMutation = useMutation({
    mutationFn: () =>
      api.adminDataUpdates.checkStaticSkillRules(
        { limit: toNumber(staticRuleCheckLimit, 100), q: emptyToNull(staticRuleSearch) },
        adminToken || undefined,
      ),
    onSuccess: (result) => {
      setLastStaticRuleResult(result);
      setSelectedStaticRuleSkillIds(result.pending_items.map((item) => item.skill_id));
    },
  });

  const staticRuleSyncMutation = useMutation({
    mutationFn: (payload: { commit: boolean; skillIds: string[] | null }) =>
      api.adminDataUpdates.syncStaticSkillRules(
        {
          commit: payload.commit,
          skill_ids: payload.skillIds,
          q: payload.skillIds ? null : emptyToNull(staticRuleSearch),
        },
        adminToken || undefined,
      ),
    onSuccess: async (result) => {
      setLastStaticRuleResult(result);
      setSelectedStaticRuleSkillIds(result.pending_items.map((item) => item.skill_id));
      await refreshRuleQueries();
    },
  });

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
      setLastPurgeResult(result);
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

  const checkError = getApiErrorText(checkMutation.error);
  const syncError = getApiErrorText(syncMutation.error);
  const bootstrapError = getApiErrorText(bootstrapLocalMutation.error ?? bootstrapStatus.error);
  const importLocalError = getApiErrorText(importLocalMutation.error);
  const staticRuleCheckError = getApiErrorText(staticRuleCheckMutation.error);
  const staticRuleSyncError = getApiErrorText(staticRuleSyncMutation.error);
  const dataJobsError = getApiErrorText(dataUpdateJobs.error);
  const bulkError = getApiErrorText(bulkPurgeMutation.error);
  const singleError = getApiErrorText(singlePurgeMutation.error);
  const syncLimitedRefreshCommitBlocked = syncUpdateMode === "full" && toNumber(syncLimit, 0) > 0;
  const pendingStaticRuleSkillCount = lastStaticRuleResult?.pending_skill_count ?? 0;
  const pendingStaticRuleEffectCount = lastStaticRuleResult?.pending_effect_count ?? 0;
  const canSyncSelectedStaticRules =
    selectedStaticRuleSkillIds.length > 0
    || (pendingStaticRuleSkillCount === 0 && pendingStaticRuleEffectCount > 0);
  const selectedStaticRulePayload =
    selectedStaticRuleSkillIds.length > 0 ? selectedStaticRuleSkillIds : null;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">设置 / 数据管理</h1>
        <p className="mt-1 text-muted-foreground">连接状态、静态规则数据更新与归档战斗清理。</p>
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
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={health.data?.status === "ok" ? "success" : health.isError ? "destructive" : "secondary"}>
              health: {health.data?.status ?? "unknown"}
            </Badge>
            <Button variant="outline" size="sm" onClick={() => health.refetch()}>重新检测</Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>管理令牌</CardTitle>
          <CardDescription>
            数据更新和物理清理都会修改或影响本地数据库。若后端配置了 `ADMIN_UPDATE_TOKEN`，这里必须填写匹配的令牌。
          </CardDescription>
        </CardHeader>
        <CardContent>
          <label className="block max-w-xl space-y-1">
            <span className="text-sm font-medium">Admin Token</span>
            <Input
              type="password"
              value={adminToken}
              placeholder="后端未配置 ADMIN_UPDATE_TOKEN 时可留空"
              onChange={(event) => setAdminToken(event.target.value)}
            />
          </label>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>静态规则数据库更新</CardTitle>
          <CardDescription>
            一般新 clone 项目时本地数据库可能为空。这里可以主动检查 BWIKI 更新、从远程爬取并导入，或从本地 cleaned JSON 导入。
            推荐先 dry-run 预览，再确认提交写库。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="rounded-2xl border bg-amber-50 p-4 text-sm text-amber-900">
            爬虫更新不是常驻服务，也不会随后端启动自动运行。日常使用只启动前后端；只有本地规则库为空或需要更新精灵/技能数据时，才在这里主动触发。
          </div>

          <section className="space-y-3 rounded-2xl border bg-white p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h3 className="font-semibold">0. 新用户 / 空库一键初始化</h3>
                <p className="mt-1 text-sm text-muted-foreground">
                  会一次性补齐核心性格、默认聚能技能、BWIKI 静态数据、状态定义 seed 和人工技能分支 seed。
                  优先使用本地 cleaned 数据包，不访问远程，适合发给新用户快速初始化。
                </p>
              </div>
              <Button variant="outline" onClick={() => bootstrapStatus.refetch()}>
                刷新数据状态
              </Button>
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              <label className="space-y-1">
                <span className="text-sm font-medium">本地 cleaned 数据包目录</span>
                <Input
                  value={bootstrapCleanedDir}
                  placeholder="留空 = 后端 ROCOM_DATA_DIR/cleaned"
                  onChange={(event) => setBootstrapCleanedDir(event.target.value)}
                />
              </label>
              <label className="space-y-1">
                <span className="text-sm font-medium">覆盖 data_version</span>
                <Input
                  value={bootstrapDataVersion}
                  placeholder="可选，例如 rocom_bwiki_20260609"
                  onChange={(event) => setBootstrapDataVersion(event.target.value)}
                />
              </label>
            </div>

            {bootstrapStatus.data ? <BootstrapStatusPanel status={bootstrapStatus.data} /> : null}
            {bootstrapError ? <ErrorBox text={bootstrapError} /> : null}

            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                onClick={() => bootstrapLocalMutation.mutate(false)}
                disabled={Boolean(runningJob) || bootstrapLocalMutation.isPending}
              >
                预检查一键初始化（dry-run）
              </Button>
              <Button
                onClick={() => {
                  if (window.confirm("确认执行空库一键初始化并写入数据库？建议先 dry-run 检查结果。")) {
                    bootstrapLocalMutation.mutate(true);
                  }
                }}
                disabled={
                  Boolean(runningJob) ||
                  bootstrapLocalMutation.isPending ||
                  bootstrapStatus.data?.local_package_ready === false ||
                  bootstrapStatus.data?.seed_files.some((file) => !file.exists) === true
                }
              >
                一键初始化本地数据库
              </Button>
            </div>
            {bootstrapLocalMutation.isPending ? <InlineProgressBar label="正在创建初始化任务..." /> : null}
          </section>

          <section className="space-y-3 rounded-2xl border bg-white p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h3 className="font-semibold">1. 检查远程是否可能有新增精灵</h3>
                <p className="mt-1 text-sm text-muted-foreground">只解析图鉴列表，不抓取详情、不写库；适合快速判断是否需要同步。</p>
              </div>
              <Button onClick={() => checkMutation.mutate()} disabled={checkMutation.isPending}>
                {checkMutation.isPending ? "检查中..." : "检查更新"}
              </Button>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <label className="space-y-1">
                <span className="text-sm font-medium">检查前 N 条</span>
                <Input
                  value={checkLimit}
                  placeholder="0 = 全量"
                  onChange={(event) => setCheckLimit(event.target.value.replace(/[^0-9]/g, ""))}
                />
              </label>
              <label className="space-y-1">
                <span className="text-sm font-medium">新增精灵预览上限</span>
                <Input
                  value={checkPreviewLimit}
                  placeholder="默认 50"
                  onChange={(event) => setCheckPreviewLimit(event.target.value.replace(/[^0-9]/g, ""))}
                />
              </label>
            </div>
            {checkError ? <ErrorBox text={checkError} /> : null}
            {lastCheckResult ? <RocomCheckResultPanel result={lastCheckResult} /> : null}
          </section>

          <section className="space-y-3 rounded-2xl border bg-white p-4">
            <div>
              <h3 className="font-semibold">2. 从本地 cleaned JSON 导入数据库</h3>
              <p className="mt-1 text-sm text-muted-foreground">
                如果你已经通过爬虫或其他方式生成了 cleaned JSON，优先用这个入口。它不访问远程，速度更稳定；
                提交时会在同一事务内补齐项目内置状态定义和人工技能规则。
              </p>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <label className="space-y-1">
                <span className="text-sm font-medium">cleaned 目录</span>
                <Input
                  value={localCleanedDir}
                  placeholder="留空 = 后端 ROCOM_DATA_DIR/cleaned"
                  onChange={(event) => setLocalCleanedDir(event.target.value)}
                />
              </label>
              <label className="space-y-1">
                <span className="text-sm font-medium">覆盖 data_version</span>
                <Input
                  value={localDataVersion}
                  placeholder="可选，例如 rocom_bwiki_20260516"
                  onChange={(event) => setLocalDataVersion(event.target.value)}
                />
              </label>
            </div>
            <div className="space-y-2 rounded-xl border bg-slate-50 p-3 text-sm">
              <div className="font-medium">导入模式</div>
              <label className="flex items-start gap-2">
                <input
                  type="radio"
                  name="local-update-mode"
                  checked={localUpdateMode === "full"}
                  onChange={() => setLocalUpdateMode("full")}
                />
                <span>全量更新：重建 BWIKI 技能关系，并软删除本地缺失的 rocom 静态项。</span>
              </label>
              <label className="flex items-start gap-2">
                <input
                  type="radio"
                  name="local-update-mode"
                  checked={localUpdateMode === "incremental"}
                  onChange={() => setLocalUpdateMode("incremental")}
                />
                <span>增量导入：不软删除旧数据，适合只补充新爬到的数据。</span>
              </label>
            </div>
            {localUpdateMode === "full" ? (
              <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
                全量提交前请先确认 cleaned JSON 是完整数据集；你当前已生成的默认 cleaned 目录会被直接导入，不会重新访问 BWIKI。
              </div>
            ) : null}
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                onClick={() => importLocalMutation.mutate(false)}
                disabled={Boolean(runningJob) || importLocalMutation.isPending}
              >
                预检查本地数据（dry-run）
              </Button>
              <Button
                onClick={() => {
                  if (window.confirm("确认把本地 cleaned JSON 写入数据库？建议先 dry-run 检查结果。")) {
                    importLocalMutation.mutate(true);
                  }
                }}
                disabled={Boolean(runningJob) || importLocalMutation.isPending}
              >
                一键导入本地数据（提交）
              </Button>
            </div>
            {importLocalMutation.isPending ? <InlineProgressBar label="正在创建本地导入任务..." /> : null}
            {importLocalError ? <ErrorBox text={importLocalError} /> : null}
          </section>

          <section className="space-y-3 rounded-2xl border bg-white p-4">
            <div>
              <h3 className="font-semibold">3. 同步已完备技能分支规则</h3>
              <p className="mt-1 text-sm text-muted-foreground">
                只检查 seed 中 review_status = structured 且没有结构缺口的技能。默认先列出还没写入数据库或与 seed 不一致的规则，
                你可以勾选后 dry-run 或提交写库；项目状态定义 seed 会随任意同步操作一起 dry-run/写库，不需要单独勾选。
              </p>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <label className="space-y-1">
                <span className="text-sm font-medium">列表上限</span>
                <Input
                  value={staticRuleCheckLimit}
                  placeholder="默认 100"
                  onChange={(event) => setStaticRuleCheckLimit(event.target.value.replace(/[^0-9]/g, ""))}
                />
              </label>
              <label className="space-y-1">
                <span className="text-sm font-medium">技能名 / ID 筛选</span>
                <Input
                  value={staticRuleSearch}
                  placeholder="例如：三连破、花炮"
                  onChange={(event) => setStaticRuleSearch(event.target.value)}
                />
              </label>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                onClick={() => staticRuleCheckMutation.mutate()}
                disabled={staticRuleCheckMutation.isPending || staticRuleSyncMutation.isPending}
              >
                {staticRuleCheckMutation.isPending ? "检查中..." : "检查待同步规则"}
              </Button>
              <Button
                variant="outline"
                onClick={() =>
                  staticRuleSyncMutation.mutate({
                    commit: false,
                    skillIds: selectedStaticRulePayload,
                  })
                }
                disabled={
                  staticRuleSyncMutation.isPending || !canSyncSelectedStaticRules
                }
              >
                预检查选中规则 / 状态定义（dry-run）
              </Button>
              <Button
                onClick={() => {
                  if (
                    window.confirm(
                      `确认写入 ${selectedStaticRuleSkillIds.length} 条已选 structured 技能规则，并同步待更新状态定义？建议先 dry-run。`,
                    )
                  ) {
                    staticRuleSyncMutation.mutate({
                      commit: true,
                      skillIds: selectedStaticRulePayload,
                    });
                  }
                }}
                disabled={
                  staticRuleSyncMutation.isPending || !canSyncSelectedStaticRules
                }
              >
                写入选中规则 / 状态定义
              </Button>
              <Button
                variant="secondary"
                onClick={() => {
                  const scopeText = staticRuleSearch.trim() ? `当前筛选“${staticRuleSearch.trim()}”下的` : "所有";
                  if (window.confirm(`确认写入${scopeText}待同步 structured 技能规则，并同步待更新状态定义？建议先查看列表。`)) {
                    staticRuleSyncMutation.mutate({ commit: true, skillIds: null });
                  }
                }}
                disabled={staticRuleSyncMutation.isPending || !lastStaticRuleResult?.pending_count}
              >
                {staticRuleSearch.trim() ? "写入当前筛选待同步" : "写入全部待同步"}
              </Button>
            </div>
            {staticRuleCheckError ? <ErrorBox text={staticRuleCheckError} /> : null}
            {staticRuleSyncError ? <ErrorBox text={staticRuleSyncError} /> : null}
            {staticRuleSyncMutation.isPending ? (
              <InlineProgressBar label="正在同步 structured 技能规则 seed..." />
            ) : null}
            {lastStaticRuleResult ? (
              <StaticSkillRuleSyncPanel
                result={lastStaticRuleResult}
                selectedSkillIds={selectedStaticRuleSkillIds}
                onSelectionChange={setSelectedStaticRuleSkillIds}
              />
            ) : null}
          </section>

          <section className="space-y-3 rounded-2xl border bg-white p-4">
            <div>
              <h3 className="font-semibold">4. 远程爬取、清洗并导入</h3>
              <p className="mt-1 text-sm text-muted-foreground">
                该操作会访问 BWIKI。默认按钮是 dry-run，不提交数据库；确认无误后再提交写库。提交时同样会补齐项目内置状态定义和人工技能规则。
              </p>
            </div>
            <div className="grid gap-3 md:grid-cols-3">
              <label className="space-y-1">
                <span className="text-sm font-medium">同步前 N 条</span>
                <Input
                  value={syncLimit}
                  placeholder="0 = 全量"
                  onChange={(event) => setSyncLimit(event.target.value.replace(/[^0-9]/g, ""))}
                />
              </label>
              <label className="space-y-1">
                <span className="text-sm font-medium">请求间隔秒</span>
                <Input
                  value={syncDelay}
                  placeholder="默认 1.5"
                  onChange={(event) => setSyncDelay(event.target.value.replace(/[^0-9.]/g, ""))}
                />
              </label>
              <label className="space-y-1">
                <span className="text-sm font-medium">data_version</span>
                <Input
                  value={syncDataVersion}
                  placeholder="可选，例如 rocom_bwiki_20260516"
                  onChange={(event) => setSyncDataVersion(event.target.value)}
                />
              </label>
            </div>
            <div className="flex flex-wrap gap-4 text-sm">
              <label className="inline-flex items-center gap-2">
                <input type="checkbox" checked={syncForce} onChange={(event) => setSyncForce(event.target.checked)} />
                强制重爬已缓存精灵
              </label>
              <label className="inline-flex items-center gap-2">
                <input type="checkbox" checked={syncWithImages} onChange={(event) => setSyncWithImages(event.target.checked)} />
                下载图片
              </label>
              <label className="inline-flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={syncWriteArtifacts}
                  onChange={(event) => setSyncWriteArtifacts(event.target.checked)}
                />
                写 raw / cleaned 文件
              </label>
            </div>
            <div className="space-y-2 rounded-xl border bg-slate-50 p-3 text-sm">
              <div className="font-medium">远程更新模式</div>
              <label className="flex items-start gap-2">
                <input
                  type="radio"
                  name="sync-update-mode"
                  checked={syncUpdateMode === "full"}
                  onChange={() => setSyncUpdateMode("full")}
                />
                <span>全量更新：先检查远程，再完整爬取并全量刷新本地 rocom 静态数据。</span>
              </label>
              <label className="flex items-start gap-2">
                <input
                  type="radio"
                  name="sync-update-mode"
                  checked={syncUpdateMode === "new_only"}
                  onChange={() => setSyncUpdateMode("new_only")}
                />
                <span>只更新新增：先检查远程，只抓取本地还没有的新增精灵，不软删除旧数据。</span>
              </label>
            </div>
            {syncLimitedRefreshCommitBlocked ? (
              <div className="rounded-xl border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
                全量提交不能和“同步前 N 条”同时使用；请先 dry-run，或把同步前 N 条改为 0 后再提交。
              </div>
            ) : null}
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                onClick={() => syncMutation.mutate(false)}
                disabled={Boolean(runningJob) || syncMutation.isPending}
              >
                预检查远程并 dry-run
              </Button>
              <Button
                onClick={() => {
                  if (window.confirm("确认从远程爬取并写入数据库？建议先 dry-run 检查结果。")) {
                    syncMutation.mutate(true);
                  }
                }}
                disabled={Boolean(runningJob) || syncMutation.isPending || syncLimitedRefreshCommitBlocked}
              >
                一键导入远程数据（提交）
              </Button>
            </div>
            {syncMutation.isPending ? <InlineProgressBar label="正在创建远程同步任务..." /> : null}
            {syncError ? <ErrorBox text={syncError} /> : null}
          </section>

          <section className="space-y-3 rounded-2xl border bg-white p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="font-semibold">数据更新任务</h3>
                <p className="mt-1 text-sm text-muted-foreground">一键初始化、远程同步和本地导入都会创建后台任务；运行中每 1 秒自动刷新并显示进度条。</p>
              </div>
              <Button variant="outline" size="sm" onClick={() => dataUpdateJobs.refetch()}>刷新任务</Button>
            </div>
            {lastAcceptedJob ? <AcceptedJobBanner job={lastAcceptedJob} /> : null}
            {dataJobsError ? <ErrorBox text={dataJobsError} /> : null}
            <div className="space-y-2">
              {dataUpdateJobs.isLoading ? <div className="text-sm text-muted-foreground">正在加载任务...</div> : null}
              {dataUpdateJobs.data?.length === 0 ? <div className="text-sm text-muted-foreground">暂无数据更新任务。</div> : null}
              {dataUpdateJobs.data?.map((job) => <RocomJobCard key={job.job_id} job={job} />)}
            </div>
          </section>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>归档战斗物理清理</CardTitle>
          <CardDescription>
            “移除最近战斗”只是归档；这里会真正删除归档战斗及其实时估计、事件、快照、状态实例和资源记录。
            默认先 dry-run 预览，确认无误后再执行删除。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="grid grid-cols-2 gap-3">
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
          {lastPurgeResult ? <PurgeResultPanel title="批量清理结果" result={lastPurgeResult} /> : null}

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
    </div>
  );
}

function BootstrapStatusPanel({ status }: { status: ProjectDataBootstrapStatus }) {
  const seedFilesReady = status.seed_files.every((file) => file.exists);
  return (
    <div className="rounded-2xl border bg-slate-50 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="font-semibold">空库初始化数据状态</div>
        <Badge
          variant={
            status.ready ? "success" : status.local_package_ready && seedFilesReady ? "warning" : "destructive"
          }
        >
          {status.ready
            ? "已具备基础数据"
            : status.local_package_ready && seedFilesReady
              ? "可本地初始化"
              : "缺少初始化文件"}
        </Badge>
      </div>
      <div className="mt-2 text-sm text-muted-foreground">{status.recommended_action}</div>
      <div className="mt-3 grid gap-2 text-sm md:grid-cols-4">
        <InfoMini label="精灵" value={String(status.counts.elves ?? 0)} />
        <InfoMini label="技能" value={String(status.counts.skills ?? 0)} />
        <InfoMini label="可学习技能" value={String(status.counts.learnable_skills ?? 0)} />
        <InfoMini label="状态定义" value={String(status.counts.effects ?? 0)} />
      </div>
      {status.missing_required.length ? (
        <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          缺少：{status.missing_required.join("、")}
        </div>
      ) : null}
      <details className="mt-3">
        <summary className="cursor-pointer text-sm font-medium">查看必要数据清单与本地文件</summary>
        <div className="mt-3 space-y-3 text-sm">
          <div className="rounded-xl border bg-white p-3">
            <div className="font-medium">使用前必要数据</div>
            <div className="mt-2 space-y-2">
              {status.required_data.map((item) => (
                <div key={item.key} className="rounded-lg bg-slate-50 p-2">
                  <div className="font-medium">{item.name}</div>
                  <div className="text-xs text-muted-foreground">
                    来源：{item.source}；导入：{item.import_path}
                    {item.auto_on_startup ? "；后端启动会自动补齐" : ""}
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="rounded-xl border bg-white p-3">
            <div className="font-medium">本地 cleaned 目录</div>
            <div className="mt-1 break-all font-mono text-xs text-muted-foreground">
              {status.local_cleaned_dir}
            </div>
            <div className="mt-2 grid gap-2 md:grid-cols-2">
              {status.cleaned_files.map((file) => (
                <div
                  key={file.name}
                  className={file.exists ? "rounded-lg bg-emerald-50 p-2" : "rounded-lg bg-red-50 p-2"}
                >
                  <span className="font-mono text-xs">{file.name}</span>
                  <span className="ml-2 text-xs">{file.exists ? formatBytes(file.size_bytes) : "缺失"}</span>
                </div>
              ))}
            </div>
          </div>
          <div className="rounded-xl border bg-white p-3">
            <div className="font-medium">项目 seed 文件</div>
            <div className="mt-2 grid gap-2 md:grid-cols-2">
              {status.seed_files.map((file) => (
                <div
                  key={file.path}
                  className={file.exists ? "rounded-lg bg-emerald-50 p-2" : "rounded-lg bg-red-50 p-2"}
                >
                  <div className="font-mono text-xs">{file.name}</div>
                  <div className="mt-1 break-all text-xs text-muted-foreground">
                    {file.exists ? formatBytes(file.size_bytes) : "缺失"} · {file.path}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </details>
    </div>
  );
}

function RocomCheckResultPanel({ result }: { result: RocomCheckResponse }) {
  return (
    <div className="rounded-2xl border bg-slate-50 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="font-semibold">检查结果</div>
        <Badge variant={result.status === "changed" ? "warning" : "success"}>
          {result.status === "changed" ? "可能有新增" : "未发现新增"}
        </Badge>
      </div>
      <div className="mt-3 grid gap-2 text-sm md:grid-cols-4">
        <InfoMini label="远程精灵" value={String(result.remote_count)} />
        <InfoMini label="本地 rocom" value={String(result.local_rocom_count)} />
        <InfoMini label="新增精灵" value={String(result.new_elf_count)} />
        <InfoMini label="本地多余" value={String(result.missing_local_count)} />
      </div>
      <div className="mt-3 text-xs text-muted-foreground">
        检查时间：{new Date(result.checked_at).toLocaleString()} · 指纹：{result.remote_fingerprint}
      </div>
      <div className="mt-2 text-sm text-muted-foreground">{result.note}</div>
      {result.new_elves.length ? (
        <details className="mt-3">
          <summary className="cursor-pointer text-sm font-medium">查看新增精灵预览</summary>
          <div className="mt-2 max-h-56 overflow-auto rounded-xl border bg-white">
            {result.new_elves.map((elf, index) => (
              <div key={`${String(elf.elf_id)}-${index}`} className="border-b p-2 text-sm last:border-b-0">
                <span className="font-medium">{String(elf.name ?? "未知名称")}</span>
                <span className="ml-2 text-xs text-muted-foreground">{String(elf.elf_id ?? "")}</span>
              </div>
            ))}
          </div>
          {result.new_elves_truncated ? <div className="mt-2 text-xs text-muted-foreground">结果已截断，请提高预览上限查看更多。</div> : null}
        </details>
      ) : null}
    </div>
  );
}

function StaticSkillRuleSyncPanel({
  result,
  selectedSkillIds,
  onSelectionChange,
}: {
  result: StaticSkillRuleSyncResponse;
  selectedSkillIds: string[];
  onSelectionChange: (skillIds: string[]) => void;
}) {
  const selectedSet = new Set(selectedSkillIds);
  const allVisibleSelected =
    result.pending_items.length > 0 && result.pending_items.every((item) => selectedSet.has(item.skill_id));

  const toggleOne = (skillId: string) => {
    if (selectedSet.has(skillId)) {
      onSelectionChange(selectedSkillIds.filter((item) => item !== skillId));
    } else {
      onSelectionChange([...selectedSkillIds, skillId]);
    }
  };

  const toggleVisible = () => {
    if (allVisibleSelected) {
      const visible = new Set(result.pending_items.map((item) => item.skill_id));
      onSelectionChange(selectedSkillIds.filter((item) => !visible.has(item)));
      return;
    }
    onSelectionChange(Array.from(new Set([...selectedSkillIds, ...result.pending_items.map((item) => item.skill_id)])));
  };

  return (
    <div className="rounded-2xl border bg-slate-50 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="font-semibold">技能规则同步检查结果</div>
        <Badge variant={result.pending_count > 0 ? "warning" : "success"}>
          {result.pending_count > 0 ? `${result.pending_count} 条待同步` : "已同步"}
        </Badge>
      </div>
      <div className="mt-3 grid gap-2 text-sm md:grid-cols-4">
        <InfoMini label="structured" value={String(result.structured_total)} />
        <InfoMini label="已一致" value={String(result.up_to_date_count)} />
        <InfoMini label="待同步" value={String(result.pending_count)} />
        <InfoMini label="已写入" value={String(result.applied_count)} />
      </div>
      <div className="mt-3 text-xs text-muted-foreground">
        来源：{result.source} · transaction: {result.transaction}
        {result.query ? ` · 筛选：${result.query}` : ""}
      </div>
      {result.errors.length ? <ErrorBox text={result.errors.join("\n")} /> : null}
      {result.applied_skill_ids.length || result.applied_effect_ids?.length ? (
        <div className="mt-3 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">
          {result.applied_skill_ids.length ? <div>已处理技能：{result.applied_skill_ids.join("、")}</div> : null}
          {result.applied_effect_ids?.length ? <div>已处理状态定义：{result.applied_effect_ids.join("、")}</div> : null}
        </div>
      ) : null}

      {result.effect_pending_items?.length ? (
        <div className="mt-4 rounded-xl border bg-white p-3 text-sm">
          <div className="font-medium">待同步状态定义</div>
          <div className="mt-2 max-h-48 space-y-2 overflow-auto">
            {result.effect_pending_items.map((item) => (
              <div key={item.effect_id} className="rounded-lg border bg-slate-50 p-2">
                <span className="font-medium">{item.effect_name ?? item.effect_id}</span>
                <span className="ml-2 font-mono text-xs text-muted-foreground">{item.effect_id}</span>
                <span className="mt-1 block text-xs text-muted-foreground">
                  {item.source_file ? `来源：${item.source_file} · ` : ""}
                  变更字段：{item.changed_fields.join("、")}
                </span>
              </div>
            ))}
          </div>
          {result.effect_definition_sync?.pending_items_truncated ? (
            <div className="mt-2 text-xs text-muted-foreground">状态定义列表已截断，请提高列表上限查看更多。</div>
          ) : null}
        </div>
      ) : null}
      {result.pending_items.length ? (
        <div className="mt-4 space-y-2">
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={allVisibleSelected} onChange={toggleVisible} />
            选择/取消选择当前可见待同步规则
          </label>
          <div className="max-h-80 overflow-auto rounded-xl border bg-white">
            {result.pending_items.map((item) => (
              <label
                key={item.skill_id}
                className="flex cursor-pointer items-start gap-3 border-b p-3 text-sm last:border-b-0 hover:bg-slate-50"
              >
                <input
                  className="mt-1"
                  type="checkbox"
                  checked={selectedSet.has(item.skill_id)}
                  onChange={() => toggleOne(item.skill_id)}
                />
                <span className="min-w-0 flex-1">
                  <span className="font-medium">{item.skill_name}</span>
                  <span className="ml-2 font-mono text-xs text-muted-foreground">{item.skill_id}</span>
                  <span className="mt-1 block text-xs text-muted-foreground">
                    变更字段：{item.changed_fields.join("、")}
                    {item.review_notes ? ` · ${item.review_notes}` : ""}
                  </span>
                </span>
              </label>
            ))}
          </div>
          {result.pending_items_truncated ? (
            <div className="text-xs text-muted-foreground">
              待同步列表已截断，可提高列表上限或输入技能名/ID 精确筛选。
            </div>
          ) : null}
        </div>
      ) : (
        <div className="mt-3 text-sm text-muted-foreground">没有待同步的 structured 技能规则。</div>
      )}
    </div>
  );
}

function AcceptedJobBanner({ job }: { job: RocomDataUpdateAccepted }) {
  return (
    <div className="rounded-2xl border bg-emerald-50 p-3 text-sm text-emerald-900">
      <div className="font-medium">任务已创建：{job.job_id}</div>
      <div className="mt-1">{job.message}</div>
    </div>
  );
}

function InlineProgressBar({ label }: { label: string }) {
  return (
    <div className="rounded-xl border bg-slate-50 p-3">
      <div className="mb-1 text-xs text-muted-foreground">{label}</div>
      <div className="h-2 overflow-hidden rounded-full bg-slate-200">
        <div className="h-full w-1/2 animate-pulse rounded-full bg-primary" />
      </div>
    </div>
  );
}

function RocomJobCard({ job }: { job: RocomDataUpdateJobStatus }) {
  return (
    <div className="rounded-xl border bg-slate-50 p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="font-medium">{job.job_type} - {job.job_id}</div>
          <div className="mt-1 text-xs text-muted-foreground">
            Created: {new Date(job.created_at).toLocaleString()}
            {job.finished_at ? ` - Finished: ${new Date(job.finished_at).toLocaleString()}` : ""}
          </div>
        </div>
        <Badge variant={getJobBadgeVariant(job.status)}>{translateJobStatus(job.status)}</Badge>
      </div>
      {job.error ? <ErrorBox text={job.error} /> : null}
      <RocomJobProgressBar progress={job.progress} status={job.status} />
      <details className="mt-3">
        <summary className="cursor-pointer text-sm text-muted-foreground">View params / progress / result</summary>
        <pre className="mt-2 max-h-72 overflow-auto rounded-xl bg-slate-950 p-3 text-xs text-white">
          {JSON.stringify({ params: job.params, progress: job.progress, result: job.result }, null, 2)}
        </pre>
      </details>
    </div>
  );
}

function RocomJobProgressBar({
  progress,
  status,
}: {
  progress?: RocomJobProgress;
  status: RocomDataUpdateJobStatus["status"];
}) {
  const percent = clampProgressPercent(progress?.percent, status);
  const current = typeof progress?.current === "number" ? progress.current : null;
  const total = typeof progress?.total === "number" ? progress.total : null;
  const countText = current !== null && total !== null && total > 0 ? `${current}/${total}` : "";

  return (
    <div className="mt-3 space-y-1">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
        <span>
          {translateProgressStage(progress?.stage)}{progress?.message ? ` - ${progress.message}` : ""}
        </span>
        <span className="font-mono">{countText ? `${countText} - ` : ""}{percent.toFixed(0)}%</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-slate-200">
        <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${percent}%` }} />
      </div>
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
        <InfoMini label="估计" value={String(result.rows.enemy_panel_estimate ?? 0)} />
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

function ErrorBox({ text }: { text: string }) {
  return <div className="rounded-2xl border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive whitespace-pre-line">{text}</div>;
}

function toNullableNumber(value: string): number | null {
  if (!value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function toNumber(value: string, fallback: number): number {
  if (!value.trim()) return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function emptyToNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let size = value;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${size.toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}

function getJobBadgeVariant(status: RocomDataUpdateJobStatus["status"]): "secondary" | "warning" | "success" | "destructive" {
  if (status === "succeeded") return "success";
  if (status === "failed") return "destructive";
  if (status === "running") return "warning";
  return "secondary";
}

function translateJobStatus(status: RocomDataUpdateJobStatus["status"]): string {
  const dict: Record<RocomDataUpdateJobStatus["status"], string> = {
    queued: "排队中",
    running: "运行中",
    succeeded: "成功",
    failed: "失败",
  };
  return dict[status];
}

function translateProgressStage(stage?: string): string {
  const dict: Record<string, string> = {
    queued: "Queued",
    running: "Running",
    bootstrap_check: "检查初始化数据",
    ensure_core_rules: "补齐核心规则",
    fetch_sprite_list: "Fetch sprite list",
    scrape_sprites: "Scrape sprites",
    fetch_skill_list: "Fetch skill list",
    scrape_skills: "Scrape skills",
    scrape_complete: "Scrape complete",
    clean: "Clean",
    load_cleaned: "Load cleaned JSON",
    import: "Import",
    complete: "Complete",
    failed: "Failed",
  };
  return stage ? (dict[stage] ?? stage) : "Waiting";
}

function clampProgressPercent(
  percent: RocomJobProgress["percent"] | undefined,
  status: RocomDataUpdateJobStatus["status"],
): number {
  if (status === "succeeded") return 100;
  if (typeof percent !== "number" || !Number.isFinite(percent)) return 0;
  return Math.min(100, Math.max(0, percent));
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
