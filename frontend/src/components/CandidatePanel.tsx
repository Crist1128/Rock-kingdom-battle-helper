import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { compactId, formatTalentPattern, statName } from "@/lib/utils";

export function CandidatePanel({ battleId, elfId }: { battleId?: string | null; elfId?: string | null }) {
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
  const speedData = (detailQuery.data?.speed_buckets ?? []).map((bucket) => ({
    bucket: `${bucket.min_speed}-${bucket.max_speed}`,
    count: bucket.count,
    ratio: bucket.ratio,
  }));
  const natureData = detailQuery.data?.nature_distribution ?? [];
  const talentData = detailQuery.data?.talent_distribution ?? [];
  const patternData = detailQuery.data?.pattern_distribution?.slice(0, 5) ?? [];
  const topCandidates = topCandidatesQuery.data ?? [];
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

        {speedData.length > 0 ? (
          <div className="h-52 rounded-2xl border bg-white p-3">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={speedData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="bucket" />
                <YAxis />
                <Tooltip />
                <Bar dataKey="count" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <div className="rounded-2xl border bg-white p-3 text-sm text-muted-foreground">暂无速度分桶数据。</div>
        )}

        <DistributionList title="性格 Top" items={natureData.slice(0, 5).map((item) => ({ label: natureMap.get(item.nature_id) ?? compactId(item.nature_id), value: `${item.count} · ${(item.ratio * 100).toFixed(1)}%` }))} />
        <DistributionList title="个体资质组合 Top" items={patternData.map((item) => ({ label: formatTalentPattern(item.pattern), value: `${item.count} · ${(item.ratio * 100).toFixed(1)}%` }))} />
        <DistributionList title="个体资质维度统计" items={talentData.map((item) => ({ label: statName(item.stat_key), value: `有资质 ${item.non_zero_count} · 无资质 ${item.zero_count}` }))} />

        <div className="rounded-2xl border bg-white p-3">
          <div className="mb-2 text-sm font-semibold">候选 Top 5（按置信度）</div>
          {topCandidates.length === 0 ? <div className="text-sm text-muted-foreground">暂无候选明细。</div> : null}
          <div className="space-y-2">
            {topCandidates.map((candidate, index) => (
              <div key={candidate.candidate_id} className="rounded-xl border bg-slate-50 p-2 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">#{index + 1} {compactId(candidate.candidate_id)}</span>
                  <span className="text-muted-foreground">{((candidate.confidence ?? 0) * 100).toFixed(1)}%</span>
                </div>
                <div className="mt-1 grid grid-cols-3 gap-1 text-muted-foreground">
                  <span>评分 {candidate.match_score.toFixed(2)}</span>
                  <span>HP {candidate.final_hp}</span>
                  <span>速 {candidate.final_speed}</span>
                  <span>物防 {candidate.final_physical_defense}</span>
                  <span>魔防 {candidate.final_magic_defense}</span>
                  <span>{candidate.is_excluded ? "已排除" : "有效"}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

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

        <Button className="w-full" variant="outline" onClick={() => { summaryQuery.refetch(); detailQuery.refetch(); topCandidatesQuery.refetch(); evidenceQuery.refetch(); }}>刷新候选与证据</Button>
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
