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
  source: "default_config" | "expanded_config" | "base_talent" | "unknown";
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
  onDefaultConfigRefreshingChange,
}: {
  battleId?: string | null;
  elfId?: string | null;
  onEstimateChange?: (selection: EstimatePanelSelection) => void;
  onDefaultConfigRefreshingChange?: (refreshing: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const [defaultNatureId, setDefaultNatureId] = useState("");
  const [defaultTalents, setDefaultTalents] = useState<IndividualTalentInput>(EMPTY_TALENTS);
  const [talentMode, setTalentMode] = useState<"auto" | "manual">("auto");
  const [defaultFormTouched, setDefaultFormTouched] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const enabled = Boolean(battleId && elfId);
  const estimateQuery = useQuery({
    queryKey: ["enemy-estimate", battleId, elfId],
    queryFn: () => api.estimates.get(battleId!, elfId!),
    enabled,
  });
  const estimateEvidenceQuery = useQuery({
    queryKey: ["enemy-estimate-evidence", battleId, elfId],
    queryFn: () => api.estimates.evidence(battleId!, elfId!),
    enabled: enabled && advancedOpen,
  });
  const natures = useQuery({ queryKey: ["natures", "estimate-panel"], queryFn: () => api.natures.list({ limit: 100 }) });
  const natureMap = useMemo(() => new Map((natures.data ?? []).map((nature) => [nature.nature_id, nature.nature_name])), [natures.data]);
  const updateDefaultConfigMutation = useMutation({
    onMutate: () => {
      onDefaultConfigRefreshingChange?.(true);
    },
    mutationFn: () =>
      api.estimates.updateDefaultConfig(battleId!, elfId!, {
        preset: talentMode === "auto" ? "custom_auto_talents" : "custom_manual_talents",
        nature_id: defaultNatureId,
        individual_talent_distribution: defaultTalents,
      }),
    onSuccess: async (result) => {
      queryClient.setQueryData(["enemy-estimate", battleId, elfId], result);
      setDefaultFormTouched(false);
      await queryClient.invalidateQueries({
        queryKey: ["battle-state", battleId],
        refetchType: "active",
      });
      queryClient.invalidateQueries({ queryKey: ["enemy-estimate", battleId, elfId] });
    },
    onSettled: () => {
      onDefaultConfigRefreshingChange?.(false);
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
  const relevantAttackStat = useMemo(
    () => relevantAttackStatForSelection(estimate?.stat_constraints),
    [estimate?.stat_constraints],
  );
  const availableNatures = useMemo(
    () =>
      (natures.data ?? []).filter((nature) =>
        natureIsAllowedByConstraints(
          nature,
          preferredDefaultStat,
          disallowedPositiveStats,
          relevantAttackStat,
        ),
      ),
    [disallowedPositiveStats, natures.data, preferredDefaultStat, relevantAttackStat],
  );
  const natureGroups = useMemo(
    () => groupNaturesByPositiveStat(availableNatures, relevantAttackStat),
    [availableNatures, relevantAttackStat],
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
  const recommendedBloodlines = useMemo(
    () => stringListFromUnknown(estimate?.default_config?.recommended_bloodlines),
    [estimate?.default_config],
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
    setTalentMode("auto");
    setDefaultFormTouched(false);
    setAdvancedOpen(false);
  }, [battleId, elfId]);

  useEffect(() => {
    if (!defaultNatureId) return;
    if (!natures.data) return;
    if (!defaultNatureAllowed) {
      const estimateNatureId = estimate?.default_config
        && typeof estimate.default_config.nature_id === "string"
        ? estimate.default_config.nature_id
        : "";
      const repairedNature = availableNatures.find(
        (nature) => nature.nature_id === estimateNatureId,
      );
      setDefaultNatureId(repairedNature?.nature_id ?? "");
      setDefaultTalents(
        repairedNature
          ? parseDefaultTalents(estimate?.default_config?.individual_talent_distribution)
          : EMPTY_TALENTS,
      );
      setTalentMode("auto");
      setDefaultFormTouched(false);
    }
  }, [availableNatures, defaultNatureAllowed, defaultNatureId, estimate?.default_config, natures.data]);

  useEffect(() => {
    if (!preferredDefaultStat) return;
    if (talentMode !== "auto") return;
    setDefaultTalents((current) => {
      if (current[preferredDefaultStat] >= 7) return current;
      return { ...current, [preferredDefaultStat]: 10 };
    });
  }, [preferredDefaultStat, talentMode]);

  useEffect(() => {
    if (!estimate || defaultFormTouched) return;
    const defaultConfig = estimate.default_config;
    const natureId = defaultConfig && typeof defaultConfig.nature_id === "string"
      ? defaultConfig.nature_id
      : "";
    const natureAllowedByCurrentConstraints =
      !natureId
      || !natures.data
      || availableNatures.some((nature) => nature.nature_id === natureId);
    const talents = parseDefaultTalents(defaultConfig?.individual_talent_distribution);
    setDefaultNatureId(natureAllowedByCurrentConstraints ? natureId : "");
    setDefaultTalents(natureAllowedByCurrentConstraints ? talents : EMPTY_TALENTS);
    setTalentMode(
      defaultConfig && defaultConfig.preset === "custom_manual_talents" ? "manual" : "auto",
    );
  }, [availableNatures, defaultFormTouched, estimate, natures.data]);

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
        <CardHeader className="space-y-1 p-3">
          <CardTitle className="text-base">敌方默认配置</CardTitle>
          <CardDescription className="text-xs">选择敌方精灵后设置默认展示配置。</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const handleDefaultNatureSelect = (nextNatureId: string) => {
    const nextNature = availableNatures.find((nature) => nature.nature_id === nextNatureId);
    setDefaultNatureId(nextNatureId);
    setDefaultTalents((current) => {
      if (talentMode !== "auto") return current;
      return buildDefaultTalentsForNature(nextNature, current, relevantAttackStat);
    });
    setDefaultFormTouched(true);
  };

  return (
    <Card>
      <CardHeader className="space-y-1 p-3">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="text-base">敌方默认配置</CardTitle>
            <CardDescription className="truncate text-xs">{compactId(elfId)}</CardDescription>
          </div>
          <Badge variant={estimate?.default_config ? "success" : "outline"}>
            {estimate?.default_config ? "已设置" : "未设置"}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 p-3 pt-0">
        <div className="rounded-xl border bg-raised/60 p-3">
          <div className="grid gap-3">
            <div>
              <label className="text-sm font-medium">默认性格</label>
              <div className="mt-2 space-y-2">
                {defaultNature ? (
                  <div className="rounded-lg border border-success/25 bg-success/10 px-3 py-2 text-xs text-success">
                    当前：{defaultNature.nature_name}（+{statName(defaultNature.positive_stat)}
                    {" / -"}
                    {statName(defaultNature.negative_stat)}）
                  </div>
                ) : (
                  <div className="rounded-lg border border-dashed bg-raised/60 px-3 py-2 text-xs text-muted-foreground">
                    请选择默认性格。
                  </div>
                )}
                {natureGroups.length > 0 ? (
                  <div className="space-y-2">
                    {natureGroups.map((group) => {
                      const selectedInGroup = group.natures.some(
                        (nature) => nature.nature_id === defaultNatureId,
                      );
                      return (
                        <details
                          key={group.key}
                          className="overflow-hidden rounded-xl border bg-raised/60"
                        >
                          <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-3 py-2 text-sm transition hover:bg-raised [&::-webkit-details-marker]:hidden">
                            <span className="font-semibold text-success">
                              {group.title}
                            </span>
                            <span className="flex items-center gap-2 text-xs text-muted-foreground">
                              {selectedInGroup ? (
                                <Badge variant="success">已选</Badge>
                              ) : null}
                              <Badge variant="outline">{group.natures.length} 个</Badge>
                            </span>
                          </summary>
                          <div className="grid gap-2 p-2">
                            {group.natures.map((nature) => {
                              const selected = nature.nature_id === defaultNatureId;
                              return (
                                <button
                                  key={nature.nature_id}
                                  type="button"
                                  className={[
                                    "rounded-lg border px-3 py-2 text-left text-sm transition",
                                    selected
                                      ? "border-success bg-success/10 text-success"
                                      : "bg-raised/60 hover:border-success/25 hover:bg-success/10",
                                  ].join(" ")}
                                  onClick={() => handleDefaultNatureSelect(nature.nature_id)}
                                >
                                  <span className="font-medium">{nature.nature_name}</span>
                                  <span className="ml-2 text-xs text-muted-foreground">
                                    +{statName(nature.positive_stat)} / -
                                    {statName(nature.negative_stat)}
                                  </span>
                                </button>
                              );
                            })}
                          </div>
                        </details>
                      );
                    })}
                  </div>
                ) : (
                  <div className="rounded-xl border border-warning/25 bg-warning/10 p-3 text-xs text-warning">
                    当前约束下没有可选性格。
                  </div>
                )}
              </div>
              {disallowedPositiveStats.size > 0 ? (
                <div className="mt-1 text-xs text-muted-foreground">
                  已隐藏明显冲突性格；保存时后端会校验。
                </div>
              ) : null}
              {preferredDefaultStat ? (
                <div className="mt-1 text-xs text-success">
                  建议正修{statName(preferredDefaultStat)}，该资质至少 7。
                </div>
              ) : null}
              <div className="mt-1 flex items-center justify-between gap-2 text-xs text-muted-foreground">
                <span>
                  资质模式：{talentMode === "auto" ? "自动跟随性格" : "手动固定"}
                </span>
                {defaultNature && talentMode === "manual" ? (
                  <button
                    className="text-success underline-offset-2 hover:underline"
                    type="button"
                    onClick={() => {
                      setDefaultTalents((current) =>
                        buildDefaultTalentsForNature(defaultNature, current, relevantAttackStat),
                      );
                      setTalentMode("auto");
                      setDefaultFormTouched(true);
                    }}
                  >
                    按当前性格重置资质
                  </button>
                ) : null}
              </div>
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
                      setTalentMode("manual");
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
              <div className="rounded-xl border bg-raised/60 p-3 text-xs text-muted-foreground">
                保存后显示默认六维面板，仅用于展示。
              </div>
            )}
            <div className="rounded-xl border bg-raised/60 p-3">
              <div className="mb-2 flex items-center justify-between gap-2">
                <span className="text-sm font-medium">热门血脉</span>
                <Badge variant={recommendedBloodlines.length ? "success" : "outline"}>
                  {recommendedBloodlines.length ? `${recommendedBloodlines.length} 项` : "未记录"}
                </Badge>
              </div>
              {recommendedBloodlines.length ? (
                <div className="flex flex-wrap gap-2">
                  {recommendedBloodlines.map((bloodline) => (
                    <Badge key={bloodline} variant="outline">
                      {bloodline}
                    </Badge>
                  ))}
                </div>
              ) : (
                <div className="text-xs text-muted-foreground">
                  当前精灵暂无已导入的热门血脉培养。
                </div>
              )}
            </div>
            <Button
              variant="secondary"
              disabled={!canSaveDefaultConfig || !defaultNatureAllowed}
              onClick={() => updateDefaultConfigMutation.mutate()}
            >
              {updateDefaultConfigMutation.isPending ? "保存并刷新理论伤害中..." : "保存默认配置"}
            </Button>
            {updateDefaultConfigMutation.isPending ? (
              <div className="rounded-xl border border-info/25 bg-info/10 p-2 text-xs text-info">
                正在用新的默认配置重算工作台理论伤害，刷新完成前会隐藏旧伤害数值。
              </div>
            ) : null}
            {updateDefaultConfigMutation.error ? (
              <div className="rounded-xl border border-destructive/25 bg-destructive/10 p-2 text-xs text-destructive">
                保存失败：{String(updateDefaultConfigMutation.error.message ?? "unknown error")}
              </div>
            ) : null}
          </div>
        </div>

        <details
          className="rounded-xl border bg-raised/60 p-3 text-sm"
          open={advancedOpen}
          onToggle={(event) => setAdvancedOpen(event.currentTarget.open)}
        >
          <summary className="cursor-pointer text-xs font-medium text-foreground/80">
            高级信息：推导范围 / evidence
          </summary>
          <div className="mt-3 space-y-3">
            <div className="grid grid-cols-3 gap-2">
              <Metric label="约束" value={constraintItems.length} />
              <Metric label="未知" value={estimate?.unknown_factors?.length ?? 0} />
              <Metric label="技能" value={estimate?.confirmed_skill_ids?.length ?? 0} />
            </div>

            <div className="rounded-xl border bg-raised/60 p-3">
              <div className="mb-2 flex items-center justify-between gap-3">
                <div className="text-sm font-semibold">实时推导范围</div>
                <Badge variant={constraintItems.length > 0 ? "success" : "outline"}>
                  {constraintItems.length > 0 ? `${constraintItems.length} 项` : "等待观测"}
                </Badge>
              </div>
              {constraintItems.length === 0 ? (
                <div className="text-xs text-muted-foreground">
                  暂无可展示的属性范围。
                </div>
              ) : (
                <div className="grid gap-2">
                  {constraintItems.map((item) => (
                    <ConstraintItem key={item.statKey} item={item} />
                  ))}
                </div>
              )}
              {estimate?.unknown_factors?.length ? (
                <div className="mt-2 rounded-xl border bg-raised/60 p-2 text-xs text-muted-foreground">
                  未确定因素：{estimate.unknown_factors.slice(-4).join("；")}
                </div>
              ) : null}
            </div>

            <div className="rounded-xl border bg-raised/60 p-3">
              <div className="mb-2 flex items-center justify-between gap-3">
                <div className="text-sm font-semibold">最近 evidence</div>
                <Badge variant="outline">estimate</Badge>
              </div>
              {advancedOpen && estimateEvidenceQuery.isLoading ? (
                <div className="text-xs text-muted-foreground">读取 evidence 中...</div>
              ) : null}
              {advancedOpen && evidenceItems.length === 0 && !estimateEvidenceQuery.isLoading ? (
                <div className="text-xs text-muted-foreground">暂无实时估计 evidence。</div>
              ) : null}
              <div className="space-y-2">
                {evidenceItems.map((item, index) => (
                  <EvidenceItem key={`${String(item.evidence_id ?? "event")}-${index}`} item={item as unknown as Record<string, unknown>} />
                ))}
              </div>
            </div>

            <Button
              className="w-full"
              size="sm"
              variant="outline"
              onClick={() => {
                estimateQuery.refetch();
                estimateEvidenceQuery.refetch();
              }}
            >
              刷新高级信息
            </Button>
          </div>
        </details>
      </CardContent>
    </Card>
  );
}

function EvidenceItem({ item }: { item: Record<string, unknown> }) {
  const confidence = String(item.confidence ?? item.status ?? "recorded");
  const badgeVariant = confidence === "formula_constraint_derived" ? "success" : "warning";
  const explanation = asRecord(item.explanation);
  const formula = asRecord(explanation?.formula);
  const modifiers = asRecord(explanation?.modifiers);
  const event = asRecord(explanation?.event);
  const keyMultipliers = asRecord(formula?.key_multipliers);
  const constraintChanges = Array.isArray(explanation?.constraint_changes)
    ? explanation.constraint_changes.filter(isRecord)
    : [];
  const whyNoConstraint = Array.isArray(explanation?.why_no_constraint)
    ? explanation.why_no_constraint.map(String)
    : [];
  const conflict = asRecord(explanation?.conflict) ?? asRecord(item.conflict);
  const snapshotEffects = asRecord(modifiers?.snapshot_effects);
  const missingInputs = Array.isArray(formula?.missing_inputs) ? formula.missing_inputs : [];
  const unknownFactors = Array.isArray(item.unknown_factors) ? item.unknown_factors : [];
  const summary = typeof explanation?.summary === "string" ? explanation.summary : null;
  return (
    <div className="rounded-xl border bg-raised/60 p-2 text-xs">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate font-medium">{String(item.observation_type ?? "observation")}</span>
        <Badge variant={badgeVariant}>{formatConstraintStatus(confidence)}</Badge>
      </div>
      <div className="mt-1 grid grid-cols-2 gap-1 text-muted-foreground">
        <span className="truncate">事件 {compactId(String(item.source_event_id ?? ""))}</span>
        <span>快照 {compactId(String(event?.snapshot_id ?? "")) || "--"}</span>
        <span>推导 {formatEvidenceValue(item.inferred_stats)}</span>
        <span>未知 {unknownFactors.length}</span>
      </div>
      {summary ? <div className="mt-1 text-foreground/80">{summary}</div> : null}
      {formula ? (
        <div className="mt-1 grid grid-cols-2 gap-1 text-muted-foreground">
          <span>公式 {String(formula.type ?? "--")}</span>
          <span>技能 {compactId(String(formula.skill_id ?? "")) || "--"}</span>
          <span>分类 {String(formula.skill_category ?? "--")}</span>
          <span>缺项 {missingInputs.length}</span>
        </div>
      ) : null}
      {keyMultipliers ? <KeyMultiplierExplanation multipliers={keyMultipliers} /> : null}
      {modifiers ? (
        <div className="mt-1 grid grid-cols-2 gap-1 text-muted-foreground">
          <span>快照状态 {String(snapshotEffects?.active_effect_count ?? 0)}</span>
          <span>防守相关 {String(snapshotEffects?.defender_effect_count ?? 0)}</span>
          <span>场地/天气 {String(snapshotEffects?.field_effect_count ?? 0)}</span>
          <span>未映射 {String(modifiers.unmapped_effect_modifier_count ?? 0)}</span>
        </div>
      ) : null}
      {modifiers ? <ModifierExplanation modifiers={modifiers} /> : null}
      {constraintChanges.length ? <ConstraintChangeExplanation changes={constraintChanges} /> : null}
      {conflict ? <ConflictExplanation conflict={conflict} /> : null}
      {whyNoConstraint.length ? (
        <div className="mt-1 truncate text-warning">
          未收窄：{whyNoConstraint.slice(0, 3).join("；")}
        </div>
      ) : null}
      {unknownFactors.length ? (
        <div className="mt-1 truncate text-warning">
          未知：{unknownFactors.slice(0, 3).map(String).join("；")}
        </div>
      ) : null}
      <div className="mt-1 truncate text-muted-foreground">
        约束 {formatEvidenceValue(item.constraint_delta)}
      </div>
    </div>
  );
}

function KeyMultiplierExplanation({ multipliers }: { multipliers: Record<string, unknown> }) {
  const items = [
    ["威力", multipliers.base_power ?? multipliers.display_power],
    ["本系", multipliers.stab_multiplier],
    ["克制", multipliers.type_multiplier],
    ["天气", multipliers.weather_multiplier],
    ["应对", multipliers.response_multiplier],
    ["因子", multipliers.formula_factor],
  ]
    .filter(([, value]) => value !== null && value !== undefined)
    .map(([label, value]) => `${label} ${String(value)}`);
  if (items.length === 0) return null;
  return (
    <div className="mt-1 truncate text-muted-foreground">
      倍率：{items.join(" / ")}
    </div>
  );
}

function ModifierExplanation({ modifiers }: { modifiers: Record<string, unknown> }) {
  const lines = buildModifierExplanationLines(modifiers);
  if (lines.length === 0) return null;
  return (
    <div className="mt-2 space-y-1 rounded-lg border bg-raised/60 p-2 text-foreground/80">
      {lines.map((line) => (
        <div key={line}>{line}</div>
      ))}
    </div>
  );
}

function ConstraintChangeExplanation({ changes }: { changes: Record<string, unknown>[] }) {
  const lines = changes
    .map((change) => {
      const statKey = asString(change.stat_key);
      const outcome = asString(change.outcome);
      const merged = asRecord(change.merged);
      if (!statKey) return null;
      return `${statName(statKey)} ${formatConstraintOutcome(outcome)} ${formatConstraintRange(merged ?? {})}`;
    })
    .filter((line): line is string => Boolean(line));
  if (lines.length === 0) return null;
  return (
    <div className="mt-2 space-y-1 rounded-lg border bg-raised/60 p-2 text-foreground/80">
      {lines.slice(0, 4).map((line) => (
        <div key={line}>{line}</div>
      ))}
    </div>
  );
}

function ConflictExplanation({ conflict }: { conflict: Record<string, unknown> }) {
  const conflicts = Array.isArray(conflict.conflicts) ? conflict.conflicts.filter(isRecord) : [];
  if (conflicts.length === 0) return null;
  const first = conflicts[0];
  const statKey = asString(first.stat_key);
  const reason = asString(first.reason);
  return (
    <div className="mt-1 text-destructive">
      冲突：{statKey ? statName(statKey) : "属性约束"} {reason ?? "需要人工复核"}
    </div>
  );
}

function buildModifierExplanationLines(modifiers: Record<string, unknown>): string[] {
  const lines: string[] = [];
  const weather = asRecord(modifiers.weather);
  if (weather) {
    const effectName = asString(weather.effect_name) ?? asString(weather.effect_id) ?? "天气";
    const value = asString(weather.value);
    const source = asString(weather.source);
    if (source === "weather_skill_modifier" && value) {
      lines.push(`${effectName}：本次技能天气倍率 ${value}`);
    } else if (source === "weather_effect_no_damage_bonus") {
      lines.push(`${effectName}：已识别天气，本次不修改攻击伤害`);
    } else if (value) {
      lines.push(`${effectName}：天气倍率 ${value}`);
    }
  }

  const statStage = asRecord(modifiers.stat_stage_multiplier);
  if (statStage) {
    const value = asString(statStage.value);
    const items = Array.isArray(statStage.items) ? statStage.items.filter(isRecord) : [];
    const itemText = items
      .map((item) => {
        const name = asString(item.effect_name) ?? asString(item.effect_id) ?? "属性状态";
        const stat = asString(item.stat);
        const modifierValue = asString(item.value);
          return `${name}${stat ? ` ${statName(stat)}` : ""}${modifierValue ? ` ${formatSignedPercentModifier(modifierValue)}` : ""}`;
      })
      .join("；");
    lines.push(`${itemText || "属性修正"}：能力等级倍率 ${value ?? "--"}`);
  }

  const reductions = asRecord(modifiers.damage_reductions);
  if (reductions) {
    const items = Array.isArray(reductions.items) ? reductions.items.filter(isRecord) : [];
    if (items.length > 0) {
      const text = items
        .map((item) => {
          const name = asString(item.source_name) ?? asString(item.source_id) ?? "减伤";
          const reduction = asString(item.reduction);
          return `${name}${reduction ? ` 减伤 ${formatPercentValue(reduction)}` : ""}`;
        })
        .join("；");
      lines.push(text);
    }
  }
  return lines;
}

function formatSignedPercentModifier(value: string) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return value;
  const percent = numeric * 100;
  const sign = percent > 0 ? "+" : "";
  return `${sign}${Number.isInteger(percent) ? percent : percent.toFixed(1)}%`;
}

function formatPercentValue(value: string) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return value;
  const percent = numeric * 100;
  return `${Number.isInteger(percent) ? percent : percent.toFixed(1)}%`;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function stringListFromUnknown(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item).trim()).filter(Boolean);
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
    <div className="rounded-xl border bg-raised/60 p-2 text-xs">
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
  if (status === "constraint_conflict") return "冲突";
  return status || "--";
}

function formatConstraintOutcome(outcome: string | undefined) {
  if (outcome === "new_constraint") return "新增";
  if (outcome === "narrowed_constraint") return "收窄为";
  if (outcome === "confirmed_existing_constraint") return "确认";
  if (outcome === "conflict") return "冲突";
  if (outcome === "recorded_without_numeric_constraint") return "记录待公式";
  return outcome ?? "记录";
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

interface NatureGroup {
  key: string;
  title: string;
  natures: NatureDefinitionOut[];
}

const NATURE_GROUP_ORDER = [
  "physical_attack",
  "magic_attack",
  "speed",
  "hp",
  "physical_defense",
  "magic_defense",
] as const;

type AttackStat = "physical_attack" | "magic_attack";

function groupNaturesByPositiveStat(
  natures: NatureDefinitionOut[],
  relevantAttackStat: AttackStat | null,
): NatureGroup[] {
  const grouped = new Map<string, NatureDefinitionOut[]>();
  for (const nature of natures) {
    const key = nature.positive_stat || "unknown";
    const current = grouped.get(key);
    if (current) {
      current.push(nature);
    } else {
      grouped.set(key, [nature]);
    }
  }
  const order = new Map<string, number>(
    NATURE_GROUP_ORDER.map((statKey, index) => [statKey, index]),
  );
  return Array.from(grouped.entries())
    .map(([key, groupNatures]) => ({
      key,
      title: key === "unknown" ? "正面未知性格" : `${statName(key)}+ 性格`,
      natures: [...groupNatures].sort((left, right) =>
        left.nature_name.localeCompare(right.nature_name, "zh-CN"),
      ),
    }))
    .sort((left, right) => {
      const leftOrder =
        naturePositiveStatPenalty(left.key, relevantAttackStat) * 100
        + (order.get(left.key) ?? 999);
      const rightOrder =
        naturePositiveStatPenalty(right.key, relevantAttackStat) * 100
        + (order.get(right.key) ?? 999);
      return leftOrder - rightOrder || left.title.localeCompare(right.title, "zh-CN");
    });
}

function buildDefaultTalentsForNature(
  nature: NatureDefinitionOut | undefined,
  current: IndividualTalentInput,
  relevantAttackStat: AttackStat | null = null,
): IndividualTalentInput {
  const talents = { ...EMPTY_TALENTS, hp: 10 };
  if (!nature) return talents;

  const positive = nature.positive_stat as keyof IndividualTalentInput;
  const negative = nature.negative_stat as keyof IndividualTalentInput;
  const add = (stat: keyof IndividualTalentInput) => {
    if (stat !== negative) talents[stat] = 10;
  };
  const safeAttack = preferredAttackStat(current, negative, relevantAttackStat);
  const safeResistance = preferredResistanceStat(current, negative);

  if (positive === "hp") {
    if (negative === "physical_defense") {
      add("magic_defense");
      add(safeAttack);
    } else if (negative === "magic_defense") {
      add("physical_defense");
      add(safeAttack);
    } else {
      add("physical_defense");
      add("magic_defense");
    }
    return talents;
  }

  add(positive);
  if (positive === "speed") {
    add(safeAttack);
  } else if (positive === "physical_attack" || positive === "magic_attack") {
    if (
      relevantAttackStat
      && relevantAttackStat !== positive
      && relevantAttackStat !== negative
    ) {
      add(relevantAttackStat);
    } else if (negative !== "speed") {
      add("speed");
    } else {
      add(safeResistance);
    }
  } else if (positive === "physical_defense") {
    add(
      relevantAttackStat && relevantAttackStat !== negative
        ? relevantAttackStat
        : negative === "magic_defense"
          ? safeAttack
          : "magic_defense",
    );
  } else if (positive === "magic_defense") {
    add(
      relevantAttackStat && relevantAttackStat !== negative
        ? relevantAttackStat
        : negative === "physical_defense"
          ? safeAttack
          : "physical_defense",
    );
  }
  return talents;
}

function preferredAttackStat(
  current: IndividualTalentInput,
  negative: keyof IndividualTalentInput,
  relevantAttackStat: AttackStat | null = null,
): "physical_attack" | "magic_attack" {
  if (relevantAttackStat && relevantAttackStat !== negative) return relevantAttackStat;
  if (negative === "physical_attack") return "magic_attack";
  if (negative === "magic_attack") return "physical_attack";
  if (current.magic_attack > current.physical_attack) return "magic_attack";
  return "physical_attack";
}

function preferredResistanceStat(
  current: IndividualTalentInput,
  negative: keyof IndividualTalentInput,
): "physical_defense" | "magic_defense" {
  if (negative === "physical_defense") return "magic_defense";
  if (negative === "magic_defense") return "physical_defense";
  if (current.magic_defense > current.physical_defense) return "magic_defense";
  return "physical_defense";
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

function relevantAttackStatForSelection(
  statConstraints: Record<string, unknown> | undefined,
): AttackStat | null {
  if (!statConstraints) return null;
  const history = Array.isArray(statConstraints.observation_history)
    ? statConstraints.observation_history.filter(isRecord)
    : [];
  for (const item of [...history].reverse()) {
    if (asString(item.enemy_role) !== "attacker") continue;
    const skillCategory = asString(item.skill_category);
    if (skillCategory === "physical") return "physical_attack";
    if (skillCategory === "magic") return "magic_attack";
  }
  for (const statKey of ["physical_attack", "magic_attack"] as const) {
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
  relevantAttackStat: AttackStat | null,
) {
  if (!nature) return true;
  if (
    preferredStat
    && preferredStat !== relevantAttackStat
    && preferredStat !== "physical_attack"
    && preferredStat !== "magic_attack"
  ) {
    return nature.positive_stat === preferredStat;
  }
  return !disallowedPositiveStats.has(nature.positive_stat);
}

function naturePositiveStatPenalty(
  positiveStat: string,
  relevantAttackStat: AttackStat | null,
): number {
  if (positiveStat === "physical_defense" || positiveStat === "magic_defense") {
    return 1;
  }
  if (!relevantAttackStat) return 0;
  const irrelevantAttackStat =
    relevantAttackStat === "physical_attack" ? "magic_attack" : "physical_attack";
  if (positiveStat === relevantAttackStat) return -1;
  if (positiveStat === irrelevantAttackStat) return 1;
  return 0;
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
    <div className="rounded-2xl border bg-raised/60 p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-lg font-semibold">{value}</div>
    </div>
  );
}
