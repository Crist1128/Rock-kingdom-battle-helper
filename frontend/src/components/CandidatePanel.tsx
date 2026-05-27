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

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <div>
            <CardTitle>候选配置</CardTitle>
            <CardDescription>{compactId(elfId)}</CardDescription>
          </div>
          <Badge variant="warning">{summary?.formula_status ?? "formula_unavailable"}</Badge>
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

        <div className="rounded-2xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          当前只展示候选池、速度分桶、性格分布和个体资质组合。真实伤害公式未接入，不会基于占位结果强排除候选。
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

        <Button className="w-full" variant="outline" onClick={() => { summaryQuery.refetch(); detailQuery.refetch(); topCandidatesQuery.refetch(); }}>刷新候选摘要</Button>
      </CardContent>
    </Card>
  );
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
