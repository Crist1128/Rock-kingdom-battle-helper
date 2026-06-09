import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { compactId, statName } from "@/lib/utils";
import type {
  IndividualTalentInput,
  NatureDefinitionOut,
  StatBlock,
} from "@/types/api";

export interface EstimatePanelSelection {
  elfId: string;
  stats: StatBlock | null;
  source: "default_config" | "base_talent" | "unknown";
  matchedCount: number;
  natureName?: string | null;
}

const EMPTY_TALENTS: IndividualTalentInput = {
  hp: 0,
  physical_attack: 0,
  physical_defense: 0,
  magic_attack: 0,
  magic_defense: 0,
  speed: 0,
};

const STAT_KEYS = [
  "hp",
  "physical_attack",
  "physical_defense",
  "magic_attack",
  "magic_defense",
  "speed",
] as const;

const TALENT_OPTIONS = [0, 7, 8, 9, 10] as const;

export function EstimatePanel({
  battleId,
  elfId,
  onEstimateChange,
}: {
  battleId?: string | null;
  elfId?: string | null;
  onEstimateChange?: (selection: EstimatePanelSelection) => void;
}) {
  const queryClient = useQueryClient();
  const [defaultNatureId, setDefaultNatureId] = useState("");
  const [defaultTalents, setDefaultTalents] = useState<IndividualTalentInput>(EMPTY_TALENTS);
  const [defaultFormTouched, setDefaultFormTouched] = useState(false);
  const enabled = Boolean(battleId && elfId);
  const estimateQuery = useQuery({
    queryKey: ["enemy-estimate", battleId, elfId],
    queryFn: () => api.estimates.get(battleId!, elfId!),
    enabled,
  });
  const estimateEvidenceQuery = useQuery({
    queryKey: ["enemy-estimate-evidence", battleId, elfId],
    queryFn: () => api.estimates.evidence(battleId!, elfId!),
    enabled,
  });
  const natures = useQuery({ queryKey: ["natures", "estimate-panel"], queryFn: () => api.natures.list({ limit: 100 }) });
  const natureMap = useMemo(() => new Map((natures.data ?? []).map((nature) => [nature.nature_id, nature.nature_name])), [natures.data]);
  const updateDefaultConfigMutation = useMutation({
    mutationFn: () =>
      api.estimates.updateDefaultConfig(battleId!, elfId!, {
        preset: "custom",
        nature_id: defaultNatureId,
        individual_talent_distribution: defaultTalents,
      }),
    onSuccess: (result) => {
      queryClient.setQueryData(["enemy-estimate", battleId, elfId], result);
      setDefaultFormTouched(false);
      queryClient.invalidateQueries({ queryKey: ["enemy-estimate", battleId, elfId] });
    },
  });

  const estimate = estimateQuery.data ?? null;
  const preferredDefaultStat = useMemo(
    () => preferredPositiveStatForSelection(estimate?.stat_constraints),
    [estimate?.stat_constraints],
  );
  const selectedStats = useMemo(
    () => panelRecordToStats(estimate?.estimated_panel),
    [estimate?.estimated_panel],
  );
  const estimateSource = estimate?.default_config
    ? "default_config"
    : estimate?.estimated_panel
      ? "base_talent"
      : "unknown";
  const evidenceItems = (estimateEvidenceQuery.data ?? []).slice(0, 6);
  const disallowedPositiveStats = useMemo(
    () => disallowedPositiveStatsForSelection(estimate?.stat_constraints),
    [estimate?.stat_constraints],
  );
  const availableNatures = useMemo(
    () =>
      (natures.data ?? []).filter((nature) =>
        natureIsAllowedByConstraints(nature, preferredDefaultStat, disallowedPositiveStats),
      ),
    [disallowedPositiveStats, natures.data, preferredDefaultStat],
  );
  const defaultNature = availableNatures.find((nature) => nature.nature_id === defaultNatureId);
  const defaultNatureAllowed =
    !defaultNatureId
    || !natures.data
    || Boolean(defaultNature);
  const defaultTalentAllowed =
    !preferredDefaultStat || defaultTalents[preferredDefaultStat] >= 7;
  const constraintItems = useMemo(
    () => buildConstraintItems(estimate?.stat_constraints),
    [estimate?.stat_constraints],
  );
  const defaultPanelItems = useMemo(
    () => buildPanelItems(estimate?.default_panel),
    [estimate?.default_panel],
  );
  const canSaveDefaultConfig = Boolean(
    defaultNatureId
    && defaultNatureAllowed
    && defaultTalentAllowed
    && !updateDefaultConfigMutation.isPending,
  );

  useEffect(() => {
    setDefaultNatureId("");
    setDefaultTalents(EMPTY_TALENTS);
    setDefaultFormTouched(false);
  }, [battleId, elfId]);

  useEffect(() => {
    if (!defaultNatureId) return;
    if (!natures.data) return;
    if (!defaultNatureAllowed) {
      setDefaultNatureId("");
      setDefaultFormTouched(true);
    }
  }, [defaultNatureAllowed, defaultNatureId, natures.data]);

  useEffect(() => {
    if (!preferredDefaultStat) return;
    setDefaultTalents((current) => {
      if (current[preferredDefaultStat] >= 7) return current;
      return { ...current, [preferredDefaultStat]: 10 };
    });
  }, [preferredDefaultStat]);

  useEffect(() => {
    if (!estimate || defaultFormTouched) return;
    const defaultConfig = estimate.default_config;
    const natureId = defaultConfig && typeof defaultConfig.nature_id === "string"
      ? defaultConfig.nature_id
      : "";
    const talents = parseDefaultTalents(defaultConfig?.individual_talent_distribution);
    setDefaultNatureId(natureId);
    setDefaultTalents(talents);
  }, [defaultFormTouched, estimate]);

  useEffect(() => {
    if (!elfId || !onEstimateChange) return;
    onEstimateChange({
      elfId,
      stats: selectedStats,
      source: estimateSource,
      matchedCount: 0,
      natureName: natureMap.get(defaultNatureId) ?? defaultNatureId,
    });
  }, [
    elfId,
    estimateSource,
    onEstimateChange,
    selectedStats,
    defaultNatureId,
    natureMap,
  ]);

  if (!battleId || !elfId) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>实时面板估计</CardTitle>
          <CardDescription>选择一只敌方精灵后查看实时面板估计。</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <div>
            <CardTitle>实时面板估计</CardTitle>
            <CardDescription>{compactId(elfId)}</CardDescription>
          </div>
          <Badge variant="success">realtime_estimate</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-3 gap-2">
          <Metric label="推导约束" value={constraintItems.length} />
          <Metric label="未知因素" value={estimate?.unknown_factors?.length ?? 0} />
          <Metric label="已确认技能" value={estimate?.confirmed_skill_ids?.length ?? 0} />
        </div>

        <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">
          当前主流程使用实时面板估计；旧候选空间和配置展开不再参与前端主展示。
        </div>

        <div className="rounded-2xl border bg-white p-3">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div className="text-sm font-semibold">实时推导范围</div>
            <Badge variant={constraintItems.length > 0 ? "success" : "outline"}>
              {constraintItems.length > 0 ? `${constraintItems.length} 项约束` : "等待观测"}
            </Badge>
          </div>
          {constraintItems.length === 0 ? (
            <div className="text-sm text-muted-foreground">
              暂无可展示的属性范围。录入包含完整上下文的普通攻击伤害后，会在这里显示低置信推导结果。
            </div>
          ) : (
            <div className="grid gap-2">
              {constraintItems.map((item) => (
                <ConstraintItem key={item.statKey} item={item} />
              ))}
            </div>
          )}
          {estimate?.unknown_factors?.length ? (
            <div className="mt-3 rounded-xl border bg-slate-50 p-2 text-xs text-muted-foreground">
              未确定因素：{estimate.unknown_factors.slice(-4).join("；")}
            </div>
          ) : null}
        </div>

        <div className="rounded-2xl border bg-white p-3">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div className="text-sm font-semibold">默认展示配置</div>
            <Badge variant={estimate?.default_config ? "success" : "outline"}>
              {estimate?.default_config ? "已设置" : "未设置"}
            </Badge>
          </div>
          <div className="grid gap-3">
            <div>
              <label className="text-sm font-medium">默认性格</label>
              <Select
                className="mt-2"
                value={defaultNatureId}
                onChange={(event) => {
                  setDefaultNatureId(event.target.value);
                  if (preferredDefaultStat) {
                    setDefaultTalents((current) => ({
                      ...current,
                      [preferredDefaultStat]:
                        current[preferredDefaultStat] >= 7
                          ? current[preferredDefaultStat]
                          : 10,
                    }));
                  }
                  setDefaultFormTouched(true);
                }}
              >
                <option value="">请选择默认性格</option>
                {availableNatures.map((nature) => (
                  <option key={nature.nature_id} value={nature.nature_id}>
                    {nature.nature_name}
                  </option>
                ))}
              </Select>
              {disallowedPositiveStats.size > 0 ? (
                <div className="mt-1 text-xs text-muted-foreground">
                  已按当前 HP/防御推导排除明显冲突的正修性格；保存时后端会再次校验完整面板。
                </div>
              ) : null}
              {preferredDefaultStat ? (
                <div className="mt-1 text-xs text-emerald-700">
                  已限制为正修{statName(preferredDefaultStat)}，且该资质至少投入 7；默认填 10，可手动调为 7-9。
                </div>
              ) : null}
            </div>
            <div className="grid grid-cols-3 gap-2">
              {STAT_KEYS.map((statKey) => (
                <label key={statKey} className="text-xs font-medium">
                  {statName(statKey)}
                  <Select
                    className="mt-1 h-9"
                    value={String(defaultTalents[statKey])}
                    onChange={(event) => {
                      setDefaultTalents((current) => ({
                        ...current,
                        [statKey]: clampTalentInput(
                          event.target.value,
                          preferredDefaultStat === statKey ? 7 : 0,
                        ),
                      }));
                      setDefaultFormTouched(true);
                    }}
                  >
                    {talentOptionsFor(statKey, preferredDefaultStat).map((value) => (
                      <option key={value} value={value}>
                        {value}
                      </option>
                    ))}
                  </Select>
                </label>
              ))}
            </div>
            {defaultPanelItems.length > 0 ? (
              <div className="grid grid-cols-3 gap-2">
                {defaultPanelItems.map((item) => (
                  <Metric key={item.statKey} label={statName(item.statKey)} value={item.value} />
                ))}
              </div>
            ) : (
              <div className="rounded-xl border bg-slate-50 p-3 text-xs text-muted-foreground">
                默认配置保存后会显示后端计算出的临时六维面板；它只用于未知时展示，不作为排除依据。
              </div>
            )}
            <Button
              variant="secondary"
              disabled={!canSaveDefaultConfig || !defaultNatureAllowed}
              onClick={() => updateDefaultConfigMutation.mutate()}
            >
              {updateDefaultConfigMutation.isPending ? "保存中..." : "保存默认配置"}
            </Button>
            {updateDefaultConfigMutation.error ? (
              <div className="rounded-xl border border-red-200 bg-red-50 p-2 text-xs text-red-700">
                保存失败：{String(updateDefaultConfigMutation.error.message ?? "unknown error")}
              </div>
            ) : null}
          </div>
        </div>

        <div className="rounded-2xl border bg-white p-3">
          <div className="mb-2 flex items-center justify-between gap-3">
            <div className="text-sm font-semibold">最近 evidence</div>
            <Badge variant="outline">estimate</Badge>
          </div>
          {evidenceItems.length === 0 ? <div className="text-sm text-muted-foreground">暂无实时估计 evidence。</div> : null}
          <div className="space-y-2">
            {evidenceItems.map((item, index) => (
              <EvidenceItem key={`${String(item.evidence_id ?? "event")}-${index}`} item={item as unknown as Record<string, unknown>} />
            ))}
          </div>
        </div>

        <Button variant="outline" onClick={() => { estimateQuery.refetch(); estimateEvidenceQuery.refetch(); }}>
          刷新实时估计
        </Button>
      </CardContent>
    </Card>
  );
}

function EvidenceItem({ item }: { item: Record<string, unknown> }) {
  const confidence = String(item.confidence ?? item.status ?? "recorded");
  const badgeVariant = confidence === "formula_constraint_derived" ? "success" : "warning";
  return (
    <div className="rounded-xl border bg-slate-50 p-2 text-xs">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate font-medium">{String(item.observation_type ?? "observation")}</span>
        <Badge variant={badgeVariant}>{formatConstraintStatus(confidence)}</Badge>
      </div>
      <div className="mt-1 grid grid-cols-2 gap-1 text-muted-foreground">
        <span className="truncate">事件 {compactId(String(item.source_event_id ?? ""))}</span>
        <span>推导 {formatEvidenceValue(item.inferred_stats)}</span>
        <span>未知 {Array.isArray(item.unknown_factors) ? item.unknown_factors.length : 0}</span>
        <span>上下文 {item.formula_context ? "有" : "无"}</span>
      </div>
      <div className="mt-1 truncate text-muted-foreground">
        约束 {formatEvidenceValue(item.constraint_delta)}
      </div>
    </div>
  );
}

interface ConstraintDisplayItem {
  statKey: string;
  rangeText: string;
  status: string;
  confidence?: string;
  sourceCount: number;
}

function ConstraintItem({ item }: { item: ConstraintDisplayItem }) {
  return (
    <div className="rounded-xl border bg-slate-50 p-2 text-xs">
      <div className="flex items-center justify-between gap-3">
        <span className="font-medium">{statName(item.statKey)}</span>
        <Badge variant={item.status === "formula_constraint_derived" ? "success" : "warning"}>
          {formatConstraintStatus(item.status)}
        </Badge>
      </div>
      <div className="mt-1 grid grid-cols-2 gap-1 text-muted-foreground">
        <span>范围 {item.rangeText}</span>
        <span>置信 {item.confidence ? formatConstraintConfidence(item.confidence) : "--"}</span>
        <span>证据 {item.sourceCount} 条</span>
      </div>
    </div>
  );
}

function buildConstraintItems(raw: Record<string, unknown> | undefined): ConstraintDisplayItem[] {
  if (!raw) return [];
  const items: ConstraintDisplayItem[] = [];
  for (const statKey of ["hp", "physical_attack", "physical_defense", "magic_attack", "magic_defense", "speed"]) {
    const entry = raw[statKey];
    if (!isRecord(entry)) continue;
    const status = asString(entry.status);
    const rangeText = formatConstraintRange(entry);
    if (!status && rangeText === "--") continue;
    const sourceIds = Array.isArray(entry.source_event_ids) ? entry.source_event_ids : [];
    items.push({
      statKey,
      rangeText,
      status: status || "observed_pending_formula",
      confidence: asString(entry.confidence),
      sourceCount: sourceIds.length,
    });
  }
  return items;
}

function formatConstraintRange(entry: Record<string, unknown>) {
  const integerMin = asFiniteNumber(entry.integer_min);
  const integerMax = asFiniteNumber(entry.integer_max);
  if (integerMin !== null && integerMax !== null) {
    return integerMin === integerMax ? String(integerMin) : `${integerMin} - ${integerMax}`;
  }
  const min = asString(entry.min);
  const max = asString(entry.max);
  if (min && max) return min === max ? min : `${min} - ${max}`;
  return "--";
}

function formatConstraintStatus(status: string) {
  if (status === "formula_constraint_derived") return "已推导";
  if (status === "observed_pending_formula") return "待公式";
  return status || "--";
}

function formatConstraintConfidence(confidence: string) {
  if (confidence === "low") return "低";
  if (confidence === "medium") return "中";
  if (confidence === "high") return "高";
  return confidence;
}

interface PanelDisplayItem {
  statKey: string;
  value: number;
}

function buildPanelItems(raw: Record<string, unknown> | null | undefined): PanelDisplayItem[] {
  if (!raw) return [];
  const items: PanelDisplayItem[] = [];
  for (const statKey of STAT_KEYS) {
    const value = asFiniteNumber(raw[statKey]);
    if (value !== null) items.push({ statKey, value });
  }
  return items;
}

function parseDefaultTalents(raw: unknown): IndividualTalentInput {
  if (!isRecord(raw)) return { ...EMPTY_TALENTS };
  const talents = { ...EMPTY_TALENTS };
  for (const statKey of STAT_KEYS) {
    talents[statKey] = clampTalentInput(raw[statKey]);
  }
  return talents;
}

function clampTalentInput(value: unknown, minValue = 0): number {
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(parsed)) return minValue;
  const truncated = Math.trunc(parsed);
  if (truncated >= 10) return 10;
  if (truncated >= 9) return 9;
  if (truncated >= 8) return 8;
  if (truncated >= 7) return 7;
  return minValue >= 7 ? 7 : 0;
}

function talentOptionsFor(
  statKey: keyof IndividualTalentInput,
  preferredStat: keyof IndividualTalentInput | null,
) {
  return preferredStat === statKey
    ? TALENT_OPTIONS.filter((value) => value >= 7)
    : TALENT_OPTIONS;
}

function preferredPositiveStatForSelection(
  statConstraints: Record<string, unknown> | undefined,
): keyof IndividualTalentInput | null {
  if (!statConstraints) return null;
  for (const statKey of ["physical_attack", "magic_attack", "speed"] as const) {
    const entry = statConstraints[statKey];
    if (!isRecord(entry)) continue;
    const status = asString(entry.status);
    const min = asFiniteNumber(entry.integer_min);
    const max = asFiniteNumber(entry.integer_max);
    if (status === "formula_constraint_derived" && min !== null && max !== null) {
      return statKey;
    }
  }
  return null;
}

function disallowedPositiveStatsForSelection(
  statConstraints: Record<string, unknown> | undefined,
): Set<string> {
  const result = new Set<string>();
  if (!statConstraints) return result;
  for (const statKey of ["hp", "physical_defense", "magic_defense"] as const) {
    const entry = statConstraints[statKey];
    if (!isRecord(entry)) continue;
    const status = asString(entry.status);
    const min = asFiniteNumber(entry.integer_min);
    const max = asFiniteNumber(entry.integer_max);
    if (status === "formula_constraint_derived" && min !== null && max !== null) {
      result.add(statKey);
    }
  }
  return result;
}

function natureIsAllowedByConstraints(
  nature: NatureDefinitionOut | undefined,
  preferredStat: keyof IndividualTalentInput | null,
  disallowedPositiveStats: Set<string>,
) {
  if (!nature) return true;
  if (preferredStat) return nature.positive_stat === preferredStat;
  return !disallowedPositiveStats.has(nature.positive_stat);
}

function formatEvidenceValue(value: unknown) {
  if (value === null || value === undefined) return "--";
  if (Array.isArray(value)) return value.join("-");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function asFiniteNumber(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return value;
}

function panelRecordToStats(raw: Record<string, unknown> | null | undefined): StatBlock | null {
  if (!raw) return null;
  const values = {
    hp: asFiniteNumber(raw.hp),
    physical_attack: asFiniteNumber(raw.physical_attack),
    physical_defense: asFiniteNumber(raw.physical_defense),
    magic_attack: asFiniteNumber(raw.magic_attack),
    magic_defense: asFiniteNumber(raw.magic_defense),
    speed: asFiniteNumber(raw.speed),
  };
  if (Object.values(values).every((value) => value === null)) return null;
  return values;
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-2xl border bg-white p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-lg font-semibold">{value}</div>
    </div>
  );
}
