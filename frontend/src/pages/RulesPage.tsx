import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { AvatarImage } from "@/components/ui/avatar";
import { compactId, dataVersionName, effectCategoryName, elementTypeName, elementTypeNames, elfElementTypes, filterDevElves, ownerScopeName, safeJsonParse, skillCategoryName, statName } from "@/lib/utils";
import type { ElfDefinitionOut } from "@/types/api";

const pageSize = 60;

export function RulesPage() {
  const [tab, setTab] = useState<"elves" | "skills" | "effects" | "natures">("elves");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [includeDev, setIncludeDev] = useState(false);

  const queryParams = { q, limit: pageSize, offset };
  const elves = useQuery({ queryKey: ["rules", "elves", q, offset], queryFn: () => api.elves.list(queryParams), enabled: tab === "elves" });
  const skills = useQuery({ queryKey: ["rules", "skills", q, offset], queryFn: () => api.skills.list(queryParams), enabled: tab === "skills" });
  const effects = useQuery({ queryKey: ["rules", "effects", q, offset], queryFn: () => api.effects.list(queryParams), enabled: tab === "effects" });
  const natures = useQuery({ queryKey: ["rules", "natures", q, offset], queryFn: () => api.natures.list(queryParams), enabled: tab === "natures" });
  const visibleElves = useMemo(() => filterDevElves(elves.data ?? [], includeDev), [elves.data, includeDev]);

  const resetSearch = (value: string) => {
    setQ(value);
    setOffset(0);
  };

  const activeLength = tab === "elves" ? visibleElves.length : tab === "skills" ? skills.data?.length ?? 0 : tab === "effects" ? effects.data?.length ?? 0 : natures.data?.length ?? 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">规则库</h1>
        <p className="mt-1 text-muted-foreground">只读展示后端数据库内容。精灵头像使用 BWIKI 远程 URL，属性字段由 element_types_json 解析。</p>
      </div>
      <Card>
        <CardContent className="flex items-end gap-3 pt-5">
          <div className="w-48"><label className="text-sm font-medium">类型</label><Select value={tab} onChange={(e) => { setTab(e.target.value as any); setOffset(0); }}><option value="elves">精灵</option><option value="skills">技能</option><option value="effects">状态</option><option value="natures">性格</option></Select></div>
          <div className="flex-1"><label className="text-sm font-medium">搜索</label><Input value={q} onChange={(e) => resetSearch(e.target.value)} placeholder="输入名称关键词，例如 迪莫 / 火" /></div>
          {tab === "elves" ? <label className="mb-2 flex items-center gap-2 text-sm"><input type="checkbox" checked={includeDev} onChange={(e) => setIncludeDev(e.target.checked)} />显示 dev 示例</label> : null}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div><CardTitle>查询结果</CardTitle><CardDescription>分页读取后端接口，每页 {pageSize} 条；当前显示 {activeLength} 条。</CardDescription></div>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - pageSize))}>上一页</Button>
              <Button variant="outline" size="sm" disabled={activeLength < pageSize} onClick={() => setOffset(offset + pageSize)}>下一页</Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {tab === "elves" && visibleElves.map((elf) => <ElfRuleCard key={elf.elf_id} elf={elf} />)}
          {tab === "skills" && skills.data?.map((skill) => <div key={skill.skill_id} className="rounded-2xl border bg-white p-4"><div className="flex items-start justify-between gap-3"><div><div className="font-semibold">{skill.skill_name}</div><div className="text-xs text-muted-foreground">{compactId(skill.skill_id)}</div></div><Badge variant="warning">{safeJsonParse<{ status?: string }>(skill.damage_rule_json, {}).status ?? "rule_placeholder"}</Badge></div><div className="mt-2 flex flex-wrap gap-2"><Badge>{skillCategoryName(skill.skill_category)}</Badge><Badge variant="outline">{elementTypeName(skill.element_type)}</Badge><Badge variant="secondary">威力 {skill.base_power ?? "--"}</Badge><Badge variant="secondary">能耗 {skill.base_energy_cost}</Badge><Badge variant="secondary">先手 {skill.priority_modifier}</Badge></div></div>)}
          {tab === "effects" && effects.data?.map((effect) => <div key={effect.effect_id} className="rounded-2xl border bg-white p-4"><div className="font-semibold">{effect.effect_name}</div><div className="text-xs text-muted-foreground">{effect.effect_id}</div><div className="mt-2 flex gap-2"><Badge>{effectCategoryName(effect.category)}</Badge><Badge variant="outline">{ownerScopeName(effect.owner_scope)}</Badge><Badge variant={effect.clear_on_switch ? "warning" : "secondary"}>{effect.clear_on_switch ? "切换清除" : "切换保留"}</Badge></div></div>)}
          {tab === "natures" && natures.data?.map((nature) => <div key={nature.nature_id} className="rounded-2xl border bg-white p-4"><div className="font-semibold">{nature.nature_name}</div><div className="text-xs text-muted-foreground">{nature.nature_id}</div><div className="mt-2 flex gap-2"><Badge variant="success">+ {statName(nature.positive_stat)} ×{nature.positive_multiplier}</Badge><Badge variant="destructive">- {statName(nature.negative_stat)} ×{nature.negative_multiplier}</Badge></div></div>)}
          {activeLength === 0 ? <div className="rounded-2xl border bg-slate-50 p-4 text-sm text-muted-foreground">暂无匹配结果。</div> : null}
        </CardContent>
      </Card>
    </div>
  );
}

function ElfRuleCard({ elf }: { elf: ElfDefinitionOut }) {
  const elements = elfElementTypes(elf);
  return (
    <div className="rounded-2xl border bg-white p-4">
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
