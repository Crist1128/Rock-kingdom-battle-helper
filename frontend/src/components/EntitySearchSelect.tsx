import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { buildEffectLayerSummary } from "@/lib/effectLayerSummary";
import type { EffectDefinitionOut, ElfDefinitionOut, SkillDefinitionOut } from "@/types/api";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { AvatarImage } from "@/components/ui/avatar";
import { cn, compactId, dataVersionName, effectCategoryName, elementTypeName, elementTypeNames, elfElementTypes, filterDevElves, ownerScopeName, skillCategoryName } from "@/lib/utils";

interface BaseProps<T> {
  label: string;
  value?: string | null;
  onChange: (id: string, item: T) => void;
  placeholder?: string;
  resultsMode?: "always" | "focus";
}

interface SkillSearchSelectProps extends BaseProps<SkillDefinitionOut> {
  elfId?: string | null;
}

export function ElfSearchSelect({
  label,
  value,
  onChange,
  placeholder,
  resultsMode = "always",
}: BaseProps<ElfDefinitionOut>) {
  const [q, setQ] = useState("");
  const { data = [], isLoading } = useQuery({ queryKey: ["elves", q], queryFn: () => api.elves.list({ q, limit: 50 }) });
  const selectedDetail = useQuery({
    queryKey: ["elf", value],
    queryFn: () => api.elves.get(value ?? ""),
    enabled: Boolean(value) && !data.some((item) => item.elf_id === value),
    retry: false,
  });
  const filtered = filterDevElves(data);
  const displayItems = filtered.length > 0 ? filtered : data;
  const selected = data.find((item) => item.elf_id === value) ?? selectedDetail.data;
  return (
    <SearchSelectShell
      label={label}
      q={q}
      setQ={setQ}
      placeholder={placeholder ?? "搜索精灵名称"}
      selectedText={selected?.elf_name ?? value ?? "未选择"}
      loading={isLoading}
      selected={Boolean(selected)}
      resultsMode={resultsMode}
    >
      {displayItems.map((elf) => {
        const elements = elfElementTypes(elf);
        const isSelected = elf.elf_id === value;
        return (
          <button
            key={elf.elf_id}
            className={cn(
              "flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left transition hover:bg-muted",
              isSelected && "border border-primary bg-primary/10 shadow-sm",
            )}
            onClick={() => onChange(elf.elf_id, elf)}
            type="button"
          >
            <AvatarImage src={elf.avatar} alt={elf.elf_name} fallback={elf.elf_name} className="h-9 w-9" />
            <span className="min-w-0 flex-1">
              <span className="block truncate font-medium">{elf.elf_name}</span>
              <span className="block truncate text-xs text-muted-foreground">{elementTypeNames(elements)} · 速度种族 {elf.base_speed_talent}</span>
            </span>
            {isSelected ? <Badge>已选</Badge> : <Badge variant={elf.data_version === "dev" ? "warning" : "outline"}>{dataVersionName(elf.data_version)}</Badge>}
          </button>
        );
      })}
      {!isLoading && displayItems.length === 0 ? <div className="px-3 py-2 text-sm text-muted-foreground">没有匹配精灵。</div> : null}
    </SearchSelectShell>
  );
}

export function SkillSearchSelect({
  label,
  value,
  onChange,
  placeholder,
  elfId,
  resultsMode = "always",
}: SkillSearchSelectProps) {
  const [q, setQ] = useState("");
  const globalSkills = useQuery({ queryKey: ["skills", q], queryFn: () => api.skills.list({ q, limit: 100 }) });
  const learnableSkills = useQuery({
    queryKey: ["elf", elfId, "skills", q],
    queryFn: () => api.elves.skills(elfId ?? "", { q, limit: 500 }),
    enabled: Boolean(elfId),
    retry: false,
  });
  const selectedDetail = useQuery({
    queryKey: ["skill", value],
    queryFn: () => api.skills.get(value ?? ""),
    enabled: Boolean(value),
    retry: false,
  });

  const canUseLearnableSkills = Boolean(elfId) && !learnableSkills.isError && (learnableSkills.data?.length ?? 0) > 0;
  const data = canUseLearnableSkills ? learnableSkills.data ?? [] : globalSkills.data ?? [];
  const selected = data.find((item) => item.skill_id === value) ?? selectedDetail.data;
  const isLoading = canUseLearnableSkills ? learnableSkills.isLoading : globalSkills.isLoading;

  return (
    <SearchSelectShell
      label={label}
      q={q}
      setQ={setQ}
      placeholder={placeholder ?? "搜索技能名称"}
      selectedText={selected?.skill_name ?? value ?? "未选择"}
      loading={isLoading}
      selected={Boolean(selected)}
      resultsMode={resultsMode}
    >
      {elfId ? (
        <div className="px-3 py-2 text-xs text-muted-foreground">
          {canUseLearnableSkills ? "当前显示所选精灵的可学习技能。" : "后端未提供精灵可学习技能接口时，会暂时退回全局技能搜索。"}
        </div>
      ) : null}
      {data.map((skill) => {
        const isSelected = skill.skill_id === value;
        return (
          <button
            key={skill.skill_id}
            className={cn(
              "flex w-full items-center justify-between gap-3 rounded-xl px-3 py-2 text-left transition hover:bg-muted",
              isSelected && "border border-primary bg-primary/10 shadow-sm",
            )}
            onClick={() => onChange(skill.skill_id, skill)}
            type="button"
          >
            <span className="min-w-0 flex-1">
              <span className="block truncate font-medium">{skill.skill_name}</span>
              <span className="block truncate text-xs text-muted-foreground">{compactId(skill.skill_id)}</span>
            </span>
            <span className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
              {isSelected ? <Badge>已选</Badge> : null}
              {elementTypeName(skill.element_type)} · {skillCategoryName(skill.skill_category)} · 能耗 {skill.base_energy_cost}
            </span>
          </button>
        );
      })}
      {!isLoading && data.length === 0 ? <div className="px-3 py-2 text-sm text-muted-foreground">没有匹配技能。</div> : null}
    </SearchSelectShell>
  );
}

export function EffectSearchSelect({
  label,
  value,
  onChange,
  placeholder,
  resultsMode = "always",
}: BaseProps<EffectDefinitionOut>) {
  const [q, setQ] = useState("");
  const { data = [], isLoading } = useQuery({ queryKey: ["effects", q], queryFn: () => api.effects.list({ q, limit: 50 }) });
  const selected = data.find((item) => item.effect_id === value);
  const selectedSummary = selected ? buildEffectLayerSummary(selected, selected.default_layers) : null;
  return (
    <SearchSelectShell
      label={label}
      q={q}
      setQ={setQ}
      placeholder={placeholder ?? "搜索状态"}
      selectedText={selectedSummary?.displayName ?? selected?.effect_name ?? value ?? "未选择"}
      loading={isLoading}
      selected={Boolean(selected)}
      resultsMode={resultsMode}
    >
      {data.map((effect) => {
        const isSelected = effect.effect_id === value;
        const summary = buildEffectLayerSummary(effect, effect.default_layers);
        return (
          <button
            key={effect.effect_id}
            className={cn("flex w-full items-center justify-between rounded-xl px-3 py-2 text-left transition hover:bg-muted", isSelected && "border border-primary bg-primary/10 shadow-sm")}
            onClick={() => onChange(effect.effect_id, effect)}
            type="button"
          >
            <span>{summary.displayName ?? effect.effect_name}</span>
            <span className="text-xs text-muted-foreground">
              {effectCategoryName(effect.category)} · {ownerScopeName(effect.owner_scope)}
              {summary.finalTexts.length > 0 ? ` · ${summary.layerText} · ${summary.finalTexts.join("；")}` : ""}
            </span>
          </button>
        );
      })}
      {!isLoading && data.length === 0 ? <div className="px-3 py-2 text-sm text-muted-foreground">没有匹配状态。</div> : null}
    </SearchSelectShell>
  );
}

function SearchSelectShell({
  label,
  q,
  setQ,
  placeholder,
  selectedText,
  loading,
  children,
  selected,
  resultsMode = "always",
}: {
  label: string;
  q: string;
  setQ: (value: string) => void;
  placeholder: string;
  selectedText: string;
  loading: boolean;
  children: React.ReactNode;
  selected: boolean;
  resultsMode?: "always" | "focus";
}) {
  const [open, setOpen] = useState(resultsMode === "always");
  const rootRef = useRef<HTMLDivElement | null>(null);
  const mutedSelected = useMemo(() => selectedText === "未选择", [selectedText]);
  const showResults = resultsMode === "always" || open;

  useEffect(() => {
    if (resultsMode !== "focus" || !open) return undefined;
    const handlePointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open, resultsMode]);

  return (
    <div ref={rootRef} className="space-y-2">
      <div className="flex items-center justify-between gap-3">
        <label className="text-sm font-medium">{label}</label>
        <span className={mutedSelected ? "max-w-[260px] truncate text-xs text-muted-foreground" : "max-w-[260px] truncate rounded-full bg-primary/10 px-2 py-1 text-xs font-semibold text-primary"}>{selectedText}</span>
      </div>
      {selected ? <div className="rounded-xl border border-primary/30 bg-primary/5 px-3 py-2 text-sm font-medium text-primary">当前已选：{selectedText}</div> : null}
      <Input
        value={q}
        onChange={(event) => setQ(event.target.value)}
        onFocus={() => setOpen(true)}
        onClick={() => setOpen(true)}
        placeholder={placeholder}
      />
      {showResults ? (
        <div className="max-h-64 space-y-1 overflow-y-auto rounded-xl border bg-white p-1">
          {loading ? <div className="px-3 py-2 text-sm text-muted-foreground">加载中...</div> : children}
          {!loading ? (
            <div className="mt-1 grid grid-cols-2 gap-1">
              <Button variant="ghost" size="sm" type="button" onClick={() => setQ("")}>清空搜索</Button>
              {resultsMode === "focus" ? (
                <Button variant="ghost" size="sm" type="button" onClick={() => setOpen(false)}>收起</Button>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
