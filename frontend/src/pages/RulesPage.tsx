import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { AvatarImage } from "@/components/ui/avatar";
import { compactId, dataVersionName, effectCategoryName, elementTypeName, elementTypeNames, elfElementTypes, filterDevElves, ownerScopeName, safeJsonParse, skillCategoryName, statName } from "@/lib/utils";
import type { ElfDefinitionOut, SkillRuleCapabilityAuditOut, SkillRuleCapabilityItem, SkillRuleReviewOut, SkillRuleReviewStatus } from "@/types/api";

const pageSize = 60;

export function RulesPage() {
  const [tab, setTab] = useState<"elves" | "skills" | "effects" | "natures" | "audit">("elves");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [includeDev, setIncludeDev] = useState(false);
  const [skillReviewStatus, setSkillReviewStatus] = useState("");
  const [adminToken, setAdminToken] = useState(() => localStorage.getItem("adminToken") ?? "");

  useEffect(() => {
    if (adminToken) localStorage.setItem("adminToken", adminToken);
    else localStorage.removeItem("adminToken");
  }, [adminToken]);

  const queryParams = { q, limit: pageSize, offset };
  const elves = useQuery({ queryKey: ["rules", "elves", q, offset], queryFn: () => api.elves.list(queryParams), enabled: tab === "elves" });
  const skills = useQuery({
    queryKey: ["rules", "skills-review", q, skillReviewStatus, offset],
    queryFn: () =>
      api.skills.review({
        ...queryParams,
        review_status: skillReviewStatus || undefined,
      }),
    enabled: tab === "skills",
  });
  const effects = useQuery({ queryKey: ["rules", "effects", q, offset], queryFn: () => api.effects.list(queryParams), enabled: tab === "effects" });
  const natures = useQuery({ queryKey: ["rules", "natures", q, offset], queryFn: () => api.natures.list(queryParams), enabled: tab === "natures" });
  const capabilityAudit = useQuery({ queryKey: ["rules", "capability-audit"], queryFn: () => api.skills.capabilityAudit(), enabled: tab === "audit" });
  const visibleElves = useMemo(() => filterDevElves(elves.data ?? [], includeDev), [elves.data, includeDev]);

  const resetSearch = (value: string) => {
    setQ(value);
    setOffset(0);
  };

  const activeLength = tab === "elves"
    ? visibleElves.length
    : tab === "skills"
      ? skills.data?.length ?? 0
      : tab === "effects"
        ? effects.data?.length ?? 0
        : tab === "audit"
          ? (capabilityAudit.data?.implemented_capabilities.length ?? 0) + (capabilityAudit.data?.pending_capabilities.length ?? 0)
          : natures.data?.length ?? 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">规则库</h1>
        <p className="mt-1 text-muted-foreground">查看静态规则，并逐条维护技能的伤害、应对和结构化效果。</p>
      </div>
      <Card>
        <CardContent className="flex items-end gap-3 pt-5">
          <div className="w-48"><label className="text-sm font-medium">类型</label><Select value={tab} onChange={(e) => { setTab(e.target.value as typeof tab); setOffset(0); }}><option value="elves">精灵</option><option value="skills">技能</option><option value="effects">状态</option><option value="natures">性格</option><option value="audit">规则能力审计</option></Select></div>
          <div className="flex-1"><label className="text-sm font-medium">搜索</label><Input value={q} disabled={tab === "audit"} onChange={(e) => resetSearch(e.target.value)} placeholder="输入名称关键词，例如 迪莫 / 火" /></div>
          {tab === "elves" ? <label className="mb-2 flex items-center gap-2 text-sm"><input type="checkbox" checked={includeDev} onChange={(e) => setIncludeDev(e.target.checked)} />显示 dev 示例</label> : null}
          {tab === "skills" ? (
            <>
              <div className="w-48">
                <label className="text-sm font-medium">审阅状态</label>
                <Select value={skillReviewStatus} onChange={(e) => { setSkillReviewStatus(e.target.value); setOffset(0); }}>
                  <option value="">全部</option>
                  <option value="unreviewed">未审阅</option>
                  <option value="structured">已结构化</option>
                  <option value="partial">部分规则</option>
                  <option value="needs_review">待确认</option>
                  <option value="ambiguous">模糊保留</option>
                </Select>
              </div>
              <div className="w-56">
                <label className="text-sm font-medium">Admin Token</label>
                <Input
                  type="password"
                  value={adminToken}
                  placeholder="未配置可留空"
                  onChange={(e) => setAdminToken(e.target.value)}
                />
              </div>
            </>
          ) : null}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div><CardTitle>{tab === "audit" ? "规则能力审计" : "查询结果"}</CardTitle><CardDescription>{tab === "audit" ? "后端实时扫描技能规则 JSON，区分已执行、已测试和仍保留接口的机制。" : `分页读取后端接口，每页 ${pageSize} 条；当前显示 ${activeLength} 条。`}</CardDescription></div>
            {tab !== "audit" ? <div className="flex gap-2">
              <Button variant="outline" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - pageSize))}>上一页</Button>
              <Button variant="outline" size="sm" disabled={activeLength < pageSize} onClick={() => setOffset(offset + pageSize)}>下一页</Button>
            </div> : null}
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {tab === "elves" && visibleElves.map((elf) => <ElfRuleCard key={elf.elf_id} elf={elf} />)}
          {tab === "skills" && skills.data?.map((skill) => (
            <SkillRuleCard key={skill.skill_id} skill={skill} adminToken={adminToken} />
          ))}
          {tab === "effects" && effects.data?.map((effect) => <div key={effect.effect_id} className="rounded-2xl border bg-raised/60 p-4"><div className="font-semibold">{effect.effect_name}</div><div className="text-xs text-muted-foreground">{effect.effect_id}</div><div className="mt-2 flex gap-2"><Badge>{effectCategoryName(effect.category)}</Badge><Badge variant="outline">{ownerScopeName(effect.owner_scope)}</Badge><Badge variant={effect.clear_on_switch ? "warning" : "secondary"}>{effect.clear_on_switch ? "切换清除" : "切换保留"}</Badge></div></div>)}
          {tab === "natures" && natures.data?.map((nature) => <div key={nature.nature_id} className="rounded-2xl border bg-raised/60 p-4"><div className="font-semibold">{nature.nature_name}</div><div className="text-xs text-muted-foreground">{nature.nature_id}</div><div className="mt-2 flex gap-2"><Badge variant="success">+ {statName(nature.positive_stat)} ×{nature.positive_multiplier}</Badge><Badge variant="destructive">- {statName(nature.negative_stat)} ×{nature.negative_multiplier}</Badge></div></div>)}
          {tab === "audit" && capabilityAudit.isLoading ? <div className="rounded-2xl border bg-raised/60 p-4 text-sm text-muted-foreground">正在审计技能规则能力...</div> : null}
          {tab === "audit" && capabilityAudit.data ? <CapabilityAuditPanel audit={capabilityAudit.data} /> : null}
          {tab === "audit" && capabilityAudit.error ? <div className="rounded-2xl border border-destructive/25 bg-destructive/10 p-4 text-sm text-destructive">审计失败：{errorText(capabilityAudit.error)}</div> : null}
          {activeLength === 0 && tab !== "audit" ? <div className="rounded-2xl border bg-raised/60 p-4 text-sm text-muted-foreground">暂无匹配结果。</div> : null}
        </CardContent>
      </Card>
    </div>
  );
}

function CapabilityAuditPanel({ audit }: { audit: SkillRuleCapabilityAuditOut }) {
  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-4">
        <AuditStat title="技能总数" value={audit.total_skills} />
        <AuditStat title="已支持操作种类" value={Object.keys(audit.executable_operation_counts).length} />
        <AuditStat title="未支持操作种类" value={Object.keys(audit.unsupported_operation_counts).length} warning={Object.keys(audit.unsupported_operation_counts).length > 0} />
        <AuditStat title="保留 Hook 种类" value={Object.keys(audit.reserved_future_hook_counts).length} warning={Object.keys(audit.reserved_future_hook_counts).length > 0} />
      </div>
      <div className="grid gap-3 xl:grid-cols-2">
        <AuditCountCard title="审阅状态" counts={audit.review_status_counts} />
        <AuditCountCard title="已执行 effect operation" counts={audit.executable_operation_counts} />
        <AuditCountCard title="已接入 future hook" counts={audit.supported_future_hook_counts} />
        <AuditCountCard title="仍保留 future hook" counts={audit.reserved_future_hook_counts} warning />
      </div>
      <CapabilitySection title="已实现并有执行链" items={audit.implemented_capabilities} />
      <CapabilitySection title="尚未实现 / 部分实现" items={audit.pending_capabilities} pending />
      {audit.risk_notes.length ? (
        <div className="rounded-2xl border border-warning/25 bg-warning/10 p-4">
          <div className="font-semibold text-warning">风险提示</div>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-warning">
            {audit.risk_notes.map((note) => <li key={note}>{note}</li>)}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function AuditStat({ title, value, warning = false }: { title: string; value: number; warning?: boolean }) {
  return (
    <div className={`rounded-2xl border p-4 ${warning ? "border-warning/25 bg-warning/10" : "bg-raised/60"}`}>
      <div className="text-sm text-muted-foreground">{title}</div>
      <div className="mt-1 text-2xl font-bold">{value}</div>
    </div>
  );
}

function AuditCountCard({ title, counts, warning = false }: { title: string; counts: Record<string, number>; warning?: boolean }) {
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  return (
    <div className="rounded-2xl border bg-raised/60 p-4">
      <div className="font-semibold">{title}</div>
      <div className="mt-3 flex flex-wrap gap-2">
        {entries.length ? entries.map(([key, value]) => (
          <Badge key={key} variant={warning ? "warning" : "secondary"}>{key}：{value}</Badge>
        )) : <span className="text-sm text-muted-foreground">无</span>}
      </div>
    </div>
  );
}

function CapabilitySection({ title, items, pending = false }: { title: string; items: SkillRuleCapabilityItem[]; pending?: boolean }) {
  return (
    <div className="space-y-2">
      <div className="font-semibold">{title}</div>
      <div className="grid gap-3 xl:grid-cols-2">
        {items.map((item) => (
          <div key={item.key} className={`rounded-2xl border p-4 ${pending ? "border-warning/25 bg-warning/10" : "bg-raised/60"}`}>
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="font-medium">{item.label}</div>
                <div className="text-xs text-muted-foreground">{item.key}</div>
              </div>
              <div className="flex shrink-0 gap-2">
                <Badge variant={item.implemented ? "success" : "warning"}>{item.implemented ? "已实现" : "未实现"}</Badge>
                <Badge variant={item.tested ? "success" : "outline"}>{item.tested ? "已测试" : "未测"}</Badge>
              </div>
            </div>
            <div className="mt-2 flex flex-wrap gap-2">
              {item.count ? <Badge variant="secondary">出现 {item.count} 次</Badge> : null}
              {item.examples.map((example) => <Badge key={example} variant="outline">{example}</Badge>)}
            </div>
            {item.notes ? <div className="mt-2 text-sm text-muted-foreground">{item.notes}</div> : null}
          </div>
        ))}
      </div>
    </div>
  );
}

function ElfRuleCard({ elf }: { elf: ElfDefinitionOut }) {
  const elements = elfElementTypes(elf);
  return (
    <div className="rounded-2xl border bg-raised/60 p-4">
      <div className="flex items-start gap-3">
        <AvatarImage src={elf.avatar} alt={elf.elf_name} fallback={elf.elf_name} className="h-14 w-14" />
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="font-semibold">{elf.elf_name}</div>
              <div className="text-xs text-muted-foreground">{compactId(elf.elf_id)}</div>
            </div>
            <Badge variant={elf.data_version === "dev" ? "warning" : "outline"}>{dataVersionName(elf.data_version)}</Badge>
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            <Badge variant="outline">{elementTypeNames(elements)}</Badge>
            <Badge variant="secondary">生命 {elf.base_hp_talent}</Badge>
            <Badge variant="secondary">物攻 {elf.base_physical_attack_talent}</Badge>
            <Badge variant="secondary">物防 {elf.base_physical_defense_talent}</Badge>
            <Badge variant="secondary">魔攻 {elf.base_magic_attack_talent}</Badge>
            <Badge variant="secondary">魔防 {elf.base_magic_defense_talent}</Badge>
            <Badge variant="secondary">速度 {elf.base_speed_talent}</Badge>
          </div>
        </div>
      </div>
    </div>
  );
}

function SkillRuleCard({ skill, adminToken }: { skill: SkillRuleReviewOut; adminToken: string }) {
  const queryClient = useQueryClient();
  const [reviewStatus, setReviewStatus] = useState<SkillRuleReviewStatus>(
    normalizeReviewStatus(skill.review_status),
  );
  const [reviewNotes, setReviewNotes] = useState(skill.review_notes ?? "");
  const [damageRuleText, setDamageRuleText] = useState(() =>
    formatRuleJson(skill.damage_rule_json, "object"),
  );
  const [hitRuleText, setHitRuleText] = useState(() => formatRuleJson(skill.hit_rule_json, "object"));
  const [effectOperationsText, setEffectOperationsText] = useState(() =>
    formatRuleJson(skill.effect_operations_json, "array"),
  );

  useEffect(() => {
    setReviewStatus(normalizeReviewStatus(skill.review_status));
    setReviewNotes(skill.review_notes ?? "");
    setDamageRuleText(formatRuleJson(skill.damage_rule_json, "object"));
    setHitRuleText(formatRuleJson(skill.hit_rule_json, "object"));
    setEffectOperationsText(formatRuleJson(skill.effect_operations_json, "array"));
  }, [skill]);

  const updateMutation = useMutation({
    mutationFn: () => {
      const damageRule = parseOptionalJsonObject(damageRuleText, "伤害/应对规则");
      const hitRule = parseOptionalJsonObject(hitRuleText, "命中/连击规则");
      const effectOperations = parseOptionalOperationArray(effectOperationsText);
      return api.skills.updateRules(
        skill.skill_id,
        {
          damage_rule: damageRule,
          hit_rule: hitRule,
          effect_operations: effectOperations,
          review_status: reviewStatus,
          review_notes: reviewNotes.trim() || null,
        },
        adminToken || undefined,
      );
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["rules", "skills-review"] }),
        queryClient.invalidateQueries({ queryKey: ["skills"] }),
      ]);
    },
  });

  const damageStatus = safeJsonParse<{ status?: string }>(skill.damage_rule_json, {}).status;
  const statusVariant = reviewStatus === "structured"
    ? "success"
    : reviewStatus === "ambiguous" || reviewStatus === "needs_review"
      ? "warning"
      : "secondary";

  return (
    <div className="rounded-2xl border bg-raised/60 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="font-semibold">{skill.skill_name}</div>
          <div className="text-xs text-muted-foreground">{compactId(skill.skill_id)}</div>
        </div>
        <Badge variant={statusVariant}>{reviewStatusName(reviewStatus)}</Badge>
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        <Badge>{skillCategoryName(skill.skill_category)}</Badge>
        <Badge variant="outline">{elementTypeName(skill.element_type)}</Badge>
        <Badge variant="secondary">威力 {skill.base_power ?? "--"}</Badge>
        <Badge variant="secondary">能耗 {skill.base_energy_cost}</Badge>
        <Badge variant="secondary">先手 {skill.priority_modifier}</Badge>
        <Badge variant={skill.has_damage_rule ? "success" : "outline"}>伤害/应对</Badge>
        <Badge variant={skill.has_effect_operations ? "success" : "outline"}>效果操作</Badge>
        <Badge variant={skill.has_hit_rule ? "success" : "outline"}>命中/连击</Badge>
        {damageStatus ? <Badge variant="warning">{damageStatus}</Badge> : null}
      </div>
      <div className="mt-3 rounded-xl border border-info/15 bg-info/10 px-3 py-2 text-xs text-info">
        <span className="font-medium">技能原文：</span>
        {skill.raw_description?.trim() || "暂无原文描述"}
      </div>
      <div className="mt-4 grid gap-3 xl:grid-cols-3">
        <label className="space-y-1">
          <span className="text-sm font-medium">伤害 / 应对规则 JSON</span>
          <textarea
            className="min-h-40 w-full rounded-md border px-3 py-2 font-mono text-xs"
            value={damageRuleText}
            placeholder='{"damage_type":"defense_modifier","damage_reduction":0.7}'
            onChange={(event) => setDamageRuleText(event.target.value)}
          />
        </label>
        <label className="space-y-1">
          <span className="text-sm font-medium">效果操作 JSON</span>
          <textarea
            className="min-h-40 w-full rounded-md border px-3 py-2 font-mono text-xs"
            value={effectOperationsText}
            placeholder='[{"op_type":"apply_effect","effect_id":"effect_x","target":"enemy"}]'
            onChange={(event) => setEffectOperationsText(event.target.value)}
          />
        </label>
        <label className="space-y-1">
          <span className="text-sm font-medium">命中 / 连击规则 JSON</span>
          <textarea
            className="min-h-40 w-full rounded-md border px-3 py-2 font-mono text-xs"
            value={hitRuleText}
            placeholder='{"damage_display_type":"single_damage"}'
            onChange={(event) => setHitRuleText(event.target.value)}
          />
        </label>
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-[220px_1fr_auto]">
        <label className="space-y-1">
          <span className="text-sm font-medium">处理状态</span>
          <Select
            value={reviewStatus}
            onChange={(event) => setReviewStatus(normalizeReviewStatus(event.target.value))}
          >
            <option value="structured">已结构化</option>
            <option value="partial">部分规则</option>
            <option value="needs_review">待确认</option>
            <option value="ambiguous">模糊保留</option>
            <option value="unreviewed">未审阅</option>
          </Select>
        </label>
        <label className="space-y-1">
          <span className="text-sm font-medium">备注</span>
          <Input
            value={reviewNotes}
            placeholder="不清楚的触发条件、目标、倍率来源写在这里"
            onChange={(event) => setReviewNotes(event.target.value)}
          />
        </label>
        <div className="flex items-end">
          <Button disabled={updateMutation.isPending} onClick={() => updateMutation.mutate()}>
            {updateMutation.isPending ? "保存中..." : "保存规则"}
          </Button>
        </div>
      </div>
      {updateMutation.error ? (
        <div className="mt-3 rounded-xl border border-destructive/25 bg-destructive/10 p-2 text-xs text-destructive">
          保存失败：{errorText(updateMutation.error)}
        </div>
      ) : null}
    </div>
  );
}

function formatRuleJson(value: string | null | undefined, expected: "object" | "array") {
  const parsed = safeJsonParse<unknown>(value, expected === "array" ? [] : {});
  if (expected === "object" && isRecord(parsed)) {
    const { manual_review: _manualReview, ...rest } = parsed;
    return Object.keys(rest).length ? JSON.stringify(rest, null, 2) : "";
  }
  if (expected === "array" && Array.isArray(parsed) && parsed.length > 0) {
    return JSON.stringify(parsed, null, 2);
  }
  return "";
}

function parseOptionalJsonObject(text: string, label: string): Record<string, unknown> | null {
  const trimmed = text.trim();
  if (!trimmed) return null;
  const parsed = JSON.parse(trimmed) as unknown;
  if (!isRecord(parsed)) throw new Error(`${label} 必须是 JSON 对象`);
  return parsed;
}

function parseOptionalOperationArray(text: string): Record<string, unknown>[] | null {
  const trimmed = text.trim();
  if (!trimmed) return null;
  const parsed = JSON.parse(trimmed) as unknown;
  if (!Array.isArray(parsed) || !parsed.every(isRecord)) {
    throw new Error("效果操作必须是 JSON 对象数组");
  }
  return parsed;
}

function normalizeReviewStatus(value: string | undefined): SkillRuleReviewStatus {
  if (
    value === "structured"
    || value === "partial"
    || value === "needs_review"
    || value === "ambiguous"
    || value === "unreviewed"
  ) {
    return value;
  }
  return "unreviewed";
}

function reviewStatusName(value: SkillRuleReviewStatus) {
  const names: Record<SkillRuleReviewStatus, string> = {
    unreviewed: "未审阅",
    structured: "已结构化",
    partial: "部分规则",
    needs_review: "待确认",
    ambiguous: "模糊保留",
  };
  return names[value];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function errorText(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}
