import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn, compactId, statName } from "@/lib/utils";

export function CandidatePanel({ battleId, elfId }: { battleId?: string | null; elfId?: string | null }) {
  const queryClient = useQueryClient();
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null);
  const enabled = Boolean(battleId && elfId);
  const summaryQuery = useQuery({
    queryKey: ["candidate-summary", battleId, elfId],
    queryFn: () => api.candidates.summary(battleId!, elfId!),
    enabled,
  });
  const detailQuery = useQuery({
    queryKey: ["candidate-detail", battleId, elfId],
    queryFn: () => api.candidates.detail(battleId!, elfId!),
    enabled,
  });
  const topCandidatesQuery = useQuery({
    queryKey: ["candidate-list", battleId, elfId, "top"],
    queryFn: () => api.candidates.list(battleId!, elfId!, { limit: 5, offset: 0 }),
    enabled,
  });
  const evidenceQuery = useQuery({
    queryKey: ["candidate-evidence", battleId, elfId],
    queryFn: () => api.candidates.evidence(battleId!, elfId!),
    enabled,
  });
  const natures = useQuery({ queryKey: ["natures", "candidate-panel"], queryFn: () => api.natures.list({ limit: 100 }) });
  const natureMap = useMemo(() => new Map((natures.data ?? []).map((nature) => [nature.nature_id, nature.nature_name])), [natures.data]);
  const generateMutation = useMutation({
    mutationFn: () => api.candidates.generate(battleId!, elfId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["candidate-summary", battleId, elfId] });
      queryClient.invalidateQueries({ queryKey: ["candidate-detail", battleId, elfId] });
      queryClient.invalidateQueries({ queryKey: ["candidate-list", battleId, elfId] });
      queryClient.invalidateQueries({ queryKey: ["candidate-evidence", battleId, elfId] });
    },
  });

  if (!battleId || !elfId) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>候选配置</CardTitle>
          <CardDescription>选择一只敌方精灵后查看候选摘要。</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const summary = summaryQuery.data ?? detailQuery.data?.summary;
  const talentData = detailQuery.data?.talent_distribution ?? [];
  const topCandidates = topCandidatesQuery.data ?? [];
  const selectedCandidate =
    topCandidates.find((candidate) => candidate.candidate_id === selectedCandidateId)
    ?? topCandidates[0]
    ?? null;
  const evidenceItems = (evidenceQuery.data?.evidence_items ?? []).slice(-6).reverse();

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <div>
            <CardTitle>候选配置</CardTitle>
            <CardDescription>{compactId(elfId)}</CardDescription>
          </div>
          <Badge variant="success">{summary?.formula_status ?? "soft_scoring"}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-3 gap-2">
          <Metric label="总候选" value={summary?.total_count ?? "--"} />
          <Metric label="有效" value={summary?.active_count ?? "--"} />
          <Metric label="排除" value={summary?.excluded_count ?? "--"} />
          <Metric label="最低速" value={summary?.min_speed ?? "--"} />
          <Metric label="最高速" value={summary?.max_speed ?? "--"} />
          <Metric label="最高置信" value={summary?.top_confidence ?? "--"} />
        </div>

        <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">
          当前可测试普通攻击、状态伤害、星陨、防御技能减伤和 Observation 软评分。候选默认只调整分数与置信度，不硬排除。
        </div>

        <div className="grid gap-3 lg:grid-cols-[1fr_1fr]">
          <div className="rounded-2xl border bg-white p-3">
            <div className="mb-2 text-sm font-semibold">性格与资质组合 Top 5</div>
            {topCandidates.length === 0 ? <div className="text-sm text-muted-foreground">暂无候选明细。</div> : null}
            <div className="space-y-2">
              {topCandidates.map((candidate, index) => {
                const selected = selectedCandidate?.candidate_id === candidate.candidate_id;
                return (
                  <button
                    key={candidate.candidate_id}
                    type="button"
                    className={cn(
                      "w-full rounded-xl border bg-slate-50 p-2 text-left text-xs transition hover:border-primary/50 hover:bg-primary/5",
                      selected && "border-primary bg-primary/10 shadow-sm",
                    )}
                    onClick={() => setSelectedCandidateId(candidate.candidate_id)}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium">
                        #{index + 1} {natureMap.get(candidate.nature_id) ?? compactId(candidate.nature_id)}
                      </span>
                      <span className="text-muted-foreground">{((candidate.confidence ?? 0) * 100).toFixed(1)}%</span>
                    </div>
                    <div className="mt-1 text-muted-foreground">
                      {formatTalentValues(candidate.individual_talent_distribution_json)}
                    </div>
                    <div className="mt-1 flex flex-wrap gap-2 text-muted-foreground">
                      <span>评分 {candidate.match_score.toFixed(2)}</span>
                      <span>{candidate.is_excluded ? "已排除" : "有效"}</span>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="rounded-2xl border bg-white p-3">
            <div className="mb-2 flex items-center justify-between gap-3">
              <div className="text-sm font-semibold">估计面板</div>
              {selectedCandidate ? <Badge variant="outline">{compactId(selectedCandidate.candidate_id)}</Badge> : null}
            </div>
            {selectedCandidate ? (
              <div className="space-y-3">
                <div className="rounded-xl border bg-slate-50 p-3 text-xs">
                  <div className="font-medium">
                    {natureMap.get(selectedCandidate.nature_id) ?? compactId(selectedCandidate.nature_id)}
                  </div>
                  <div className="mt-1 text-muted-foreground">
                    {formatTalentValues(selectedCandidate.individual_talent_distribution_json)}
                  </div>
                </div>
                <div className="grid grid-cols-3 gap-2">
                  <Metric label="生命" value={selectedCandidate.final_hp} />
                  <Metric label="物攻" value={selectedCandidate.final_physical_attack} />
                  <Metric label="物防" value={selectedCandidate.final_physical_defense} />
                  <Metric label="魔攻" value={selectedCandidate.final_magic_attack} />
                  <Metric label="魔防" value={selectedCandidate.final_magic_defense} />
                  <Metric label="速度" value={selectedCandidate.final_speed} />
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                  <span>置信度 {((selectedCandidate.confidence ?? 0) * 100).toFixed(1)}%</span>
                  <span>评分 {selectedCandidate.match_score.toFixed(2)}</span>
                </div>
              </div>
            ) : (
              <div className="text-sm text-muted-foreground">暂无可展示的候选组合。</div>
            )}
          </div>
        </div>

        <DistributionList title="个体资质维度统计" items={talentData.map((item) => ({ label: statName(item.stat_key), value: `有资质 ${item.non_zero_count} · 无资质 ${item.zero_count}` }))} />

        <div className="rounded-2xl border bg-white p-3">
          <div className="mb-2 flex items-center justify-between gap-3">
            <div className="text-sm font-semibold">最近 evidence</div>
            <Badge variant="outline">{evidenceQuery.data?.formula_status ?? "soft_scoring"}</Badge>
          </div>
          {evidenceItems.length === 0 ? <div className="text-sm text-muted-foreground">暂无 observation evidence。</div> : null}
          <div className="space-y-2">
            {evidenceItems.map((item, index) => (
              <EvidenceItem key={`${String(item.event_id ?? "event")}-${index}`} item={item} />
            ))}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <Button variant="outline" onClick={() => { summaryQuery.refetch(); detailQuery.refetch(); topCandidatesQuery.refetch(); evidenceQuery.refetch(); }}>刷新候选与证据</Button>
          <Button
            variant="secondary"
            disabled={generateMutation.isPending}
            onClick={() => {
              if (window.confirm("重新生成该敌方精灵的候选配置？现有候选记录会按后端逻辑重建。")) {
                generateMutation.mutate();
              }
            }}
          >
            {generateMutation.isPending ? "生成中..." : "重新生成候选"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function EvidenceItem({ item }: { item: Record<string, unknown> }) {
  const matched = item.matched;
  const badgeVariant = matched === true ? "success" : matched === false ? "destructive" : "warning";
  return (
    <div className="rounded-xl border bg-slate-50 p-2 text-xs">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate font-medium">{String(item.observation_type ?? "observation")}</span>
        <Badge variant={badgeVariant}>{matched === true ? "匹配" : matched === false ? "冲突" : "未知"}</Badge>
      </div>
      <div className="mt-1 grid grid-cols-2 gap-1 text-muted-foreground">
        <span className="truncate">候选 {compactId(String(item.candidate_id ?? ""))}</span>
        <span>分数 {formatNumber(item.score_delta)}</span>
        <span>观测 {formatEvidenceValue(item.observed_value)}</span>
        <span>预测 {formatEvidenceValue(item.predicted_value ?? item.predicted_range)}</span>
      </div>
      <div className="mt-1 truncate text-muted-foreground">原因 {String(item.reason ?? "--")}</div>
    </div>
  );
}

function formatNumber(value: unknown) {
  return typeof value === "number" ? value.toFixed(2) : "--";
}

function formatEvidenceValue(value: unknown) {
  if (value === null || value === undefined) return "--";
  if (Array.isArray(value)) return value.join("-");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function formatTalentValues(rawJson: string) {
  const values = parseTalentDistribution(rawJson);
  const parts = ["hp", "physical_attack", "physical_defense", "magic_attack", "magic_defense", "speed"].map(
    (key) => `${statName(key)} ${values[key] ?? 0}`,
  );
  return parts.join(" · ");
}

function parseTalentDistribution(rawJson: string): Record<string, number> {
  try {
    const parsed = JSON.parse(rawJson) as unknown;
    if (!parsed || typeof parsed !== "object") return {};
    return Object.fromEntries(
      Object.entries(parsed as Record<string, unknown>)
        .filter(([, value]) => typeof value === "number")
        .map(([key, value]) => [key, value as number]),
    );
  } catch {
    return {};
  }
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-2xl border bg-white p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-lg font-semibold">{value}</div>
    </div>
  );
}

function DistributionList({ title, items }: { title: string; items: Array<{ label: string; value: string }> }) {
  return (
    <div className="rounded-2xl border bg-white p-3">
      <div className="mb-2 text-sm font-semibold">{title}</div>
      {items.length === 0 ? <div className="text-sm text-muted-foreground">暂无数据。</div> : null}
      <div className="space-y-1">
        {items.map((item) => (
          <div key={`${item.label}-${item.value}`} className="flex items-center justify-between gap-3 text-xs">
            <span className="truncate text-muted-foreground">{item.label}</span>
            <span className="shrink-0 font-medium">{item.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
