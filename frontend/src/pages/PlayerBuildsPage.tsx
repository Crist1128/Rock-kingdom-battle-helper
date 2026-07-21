import { FormEvent, RefObject, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Textarea } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { AvatarImage } from "@/components/ui/avatar";
import { ElfSearchSelect, SkillSearchSelect } from "@/components/EntitySearchSelect";
import { StatGrid } from "@/components/StatGrid";
import { compactId, elementTypeNames, elfElementTypes, parseElementTypes, safeJsonParse, statName } from "@/lib/utils";
import { useConfirm } from "@/components/ui/confirm";
import type {
  IndividualTalentInput,
  PlayerElfBuildCreate,
  PlayerElfBuildOut,
  TeamPresetCreate,
  TeamPresetOut,
} from "@/types/api";

const statKeys = ["hp", "physical_attack", "physical_defense", "magic_attack", "magic_defense", "speed"] as const;
const emptyTalents: IndividualTalentInput = { hp: 0, physical_attack: 0, physical_defense: 0, magic_attack: 0, magic_defense: 0, speed: 0 };

export function PlayerBuildsPage() {
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const [editingBuildId, setEditingBuildId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const elfSectionRef = useRef<HTMLDivElement | null>(null);
  const natureSectionRef = useRef<HTMLDivElement | null>(null);
  const talentSectionRef = useRef<HTMLDivElement | null>(null);
  const skillSectionRef = useRef<HTMLDivElement | null>(null);

  const [form, setForm] = useState<PlayerElfBuildCreate>({
    elf_id: "",
    nature_id: "",
    individual_talent_distribution: emptyTalents,
    skill_ids: [],
    build_name: "",
    is_default: false,
    notes: "",
  });

  const builds = useQuery({ queryKey: ["player-builds"], queryFn: () => api.playerBuilds.list() });
  const natures = useQuery({ queryKey: ["natures"], queryFn: () => api.natures.list({ limit: 100 }) });
  const skills = useQuery({ queryKey: ["skills", "all-for-builds"], queryFn: () => api.skills.list({ limit: 500 }) });
  const selectedElfQuery = useQuery({
    queryKey: ["elf", form.elf_id, "build-form"],
    queryFn: () => api.elves.get(form.elf_id),
    enabled: Boolean(form.elf_id),
  });

  const skillMap = useMemo(() => new Map((skills.data ?? []).map((skill) => [skill.skill_id, skill])), [skills.data]);
  const natureMap = useMemo(() => new Map((natures.data ?? []).map((nature) => [nature.nature_id, nature])), [natures.data]);

  const selectedElf = selectedElfQuery.data;

  const mutation = useMutation({
    mutationFn: () => editingBuildId ? api.playerBuilds.update(editingBuildId, form) : api.playerBuilds.create(form),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["player-builds"] });
      resetForm();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (buildId: string) => api.playerBuilds.delete(buildId),
    onMutate: () => setDeleteError(null),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["player-builds"] });
      if (editingBuildId) resetForm();
    },
    onError: (error) => {
      if (error instanceof ApiError && (error.status === 404 || error.status === 405)) {
        setDeleteError("删除失败，请确认后端服务已更新到包含 DELETE /api/v1/player-builds/{build_id} 的版本。");
        return;
      }
      setDeleteError(error instanceof Error ? error.message : "删除失败");
    },
  });

  const resetForm = () => {
    setEditingBuildId(null);
    setDeleteError(null);
    setValidationError(null);
    setForm({ elf_id: "", nature_id: "", individual_talent_distribution: emptyTalents, skill_ids: [], build_name: "", is_default: false, notes: "" });
  };

  const scrollToSection = (target: RefObject<HTMLDivElement | null>, message: string) => {
    setValidationError(message);
    target.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  const validateBeforeSubmit = () => {
    if (!form.elf_id) {
      scrollToSection(elfSectionRef, "请先选择精灵。页面已自动定位到精灵选择区域。");
      return false;
    }
    if (!form.nature_id) {
      scrollToSection(natureSectionRef, "请先选择性格。页面已自动定位到性格选择区域。");
      return false;
    }
    const invalidTalent = statKeys.find((key) => {
      const value = form.individual_talent_distribution[key];
      return !Number.isFinite(value) || value < 0 || value > 10;
    });
    if (invalidTalent) {
      scrollToSection(talentSectionRef, `${statName(invalidTalent)}个体资质必须在 0 到 10 之间。页面已自动定位到个体资质区域。`);
      return false;
    }
    const filledSkills = form.skill_ids.filter(Boolean);
    if (filledSkills.length < 4) {
      scrollToSection(skillSectionRef, "请补齐 4 个技能槽。页面已自动定位到技能组区域。");
      return false;
    }
    if (new Set(filledSkills).size !== filledSkills.length) {
      scrollToSection(skillSectionRef, "技能槽里存在重复技能，请调整后再保存。");
      return false;
    }
    setValidationError(null);
    return true;
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!validateBeforeSubmit()) return;
    mutation.mutate();
  };

  const selectSkill = (slot: number, id: string) => {
    const next = [...form.skill_ids];
    next[slot] = id;
    setForm({ ...form, skill_ids: next });
  };

  const removeSkill = (slot: number) => {
    const next = [...form.skill_ids];
    next[slot] = "";
    setForm({ ...form, skill_ids: next });
  };

  const requestDelete = async (buildId: string, name: string) => {
    const confirmed = await confirm({
      title: "删除配置",
      description: `确认删除配置「${name}」？`,
      confirmText: "删除",
      danger: true,
    });
    if (!confirmed) return;
    deleteMutation.mutate(buildId);
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">己方配置管理</h1>
        <p className="mt-1 text-muted-foreground">己方配置是确定输入。保存后端会计算并缓存面板属性。</p>
      </div>
      {deleteError ? <div className="rounded-2xl border border-warning/25 bg-warning/10 px-4 py-3 text-sm text-warning">{deleteError}</div> : null}
      {validationError ? <div className="rounded-2xl border border-destructive/25 bg-destructive/10 px-4 py-3 text-sm text-destructive">{validationError}</div> : null}
      <div className="grid grid-cols-[1fr_540px] gap-6">
        <Card>
          <CardHeader>
            <CardTitle>配置列表</CardTitle>
            <CardDescription>{builds.data?.length ?? 0} 个配置。列表中展示中文名，ID 仅作为辅助调试信息。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {builds.data?.map((build) => {
              const elfName = build.elf_name ?? compactId(build.elf_id);
              const buildElementTypes = parseElementTypes(build.element_types_json);
              const displayName = build.build_name || `${elfName}配置`;
              const nature = natureMap.get(build.nature_id);
              return (
                <div key={build.build_id} className="rounded-2xl border bg-raised/60 p-4">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex min-w-0 gap-3">
                      <AvatarImage src={build.avatar} alt={elfName} fallback={elfName} className="h-12 w-12" />
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <div className="truncate font-semibold">{displayName}</div>
                          {build.is_default ? <Badge>默认</Badge> : null}
                        </div>
                        <div className="mt-1 truncate text-sm text-muted-foreground">{elfName}{buildElementTypes.length > 0 ? ` · ${elementTypeNames(buildElementTypes)}` : ""}</div>
                        <div className="mt-1 text-xs text-muted-foreground">性格：{nature?.nature_name ?? compactId(build.nature_id)}</div>
                        <div className="mt-1 text-xs text-muted-foreground">{compactId(build.build_id)}</div>
                      </div>
                    </div>
                    <div className="flex shrink-0 gap-2">
                      <Button variant="outline" size="sm" onClick={() => {
                        setEditingBuildId(build.build_id);
                        setDeleteError(null);
                        setValidationError(null);
                        setForm({
                          elf_id: build.elf_id,
                          nature_id: build.nature_id,
                          individual_talent_distribution: safeJsonParse(build.individual_talent_distribution_json, emptyTalents),
                          skill_ids: [...build.skill_ids],
                          build_name: build.build_name ?? "",
                          is_default: build.is_default,
                          notes: build.notes ?? "",
                        });
                      }}>编辑</Button>
                      <Button variant="destructive" size="sm" disabled={deleteMutation.isPending} onClick={() => requestDelete(build.build_id, displayName)}>删除</Button>
                    </div>
                  </div>
                  <div className="mt-4"><StatGrid statsJson={build.final_stats_json} /></div>
                  <div className="mt-3 flex flex-wrap gap-2 text-xs">
                    {build.skill_ids.length > 0 ? build.skill_ids.map((id, index) => {
                      const skill = skillMap.get(id);
                      return <Badge key={`${id}-${index}`} variant="outline">{index + 1}. {skill?.skill_name ?? compactId(id)}</Badge>;
                    }) : <Badge variant="secondary">未配置技能</Badge>}
                  </div>
                </div>
              );
            })}
            {!builds.isLoading && (builds.data?.length ?? 0) === 0 ? <div className="rounded-2xl border border-dashed p-6 text-center text-sm text-muted-foreground">暂无己方配置，请在右侧新建。</div> : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{editingBuildId ? "编辑配置" : "新建配置"}</CardTitle>
            <CardDescription>保存时会自动检查未填内容，并定位到需要补充的区域。</CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={submit}>
              <div ref={elfSectionRef}>
                <ElfSearchSelect
                  label="精灵"
                  value={form.elf_id}
                  onChange={(id) => setForm({ ...form, elf_id: id, skill_ids: [] })}
                />
              </div>
              {selectedElf ? (
                <div className="rounded-2xl border border-primary/30 bg-primary/5 p-3">
                  <div className="flex items-center gap-3">
                    <AvatarImage src={selectedElf.avatar} alt={selectedElf.elf_name} fallback={selectedElf.elf_name} className="h-12 w-12" />
                    <div>
                      <div className="font-semibold text-primary">已选择：{selectedElf.elf_name}</div>
                      <div className="text-xs text-muted-foreground">{elementTypeNames(elfElementTypes(selectedElf))} · 速度种族 {selectedElf.base_speed_talent}</div>
                    </div>
                  </div>
                </div>
              ) : null}
              <div ref={natureSectionRef}>
                <label className="text-sm font-medium">性格</label>
                <Select value={form.nature_id} onChange={(e) => setForm({ ...form, nature_id: e.target.value })}>
                  <option value="">选择性格</option>
                  {natures.data?.map((nature) => (
                    <option key={nature.nature_id} value={nature.nature_id}>{nature.nature_name}</option>
                  ))}
                </Select>
              </div>
              <div ref={talentSectionRef}>
                <label className="text-sm font-medium">个体资质</label>
                <div className="mt-2 grid grid-cols-3 gap-2">
                  {statKeys.map((key) => (
                    <div key={key}>
                      <div className="mb-1 text-xs text-muted-foreground">{statName(key)}</div>
                      <Input
                        type="number"
                        min={0}
                        max={10}
                        value={form.individual_talent_distribution[key]}
                        onFocus={(e) => e.currentTarget.select()}
                        onChange={(e) => setForm({ ...form, individual_talent_distribution: { ...form.individual_talent_distribution, [key]: Number(e.target.value) } })}
                      />
                    </div>
                  ))}
                </div>
              </div>
              <div ref={skillSectionRef} className="space-y-3">
                <div className="flex items-center justify-between gap-3">
                  <label className="text-sm font-medium">技能组</label>
                  {form.elf_id ? <span className="text-xs text-muted-foreground">当前精灵：{selectedElf?.elf_name ?? compactId(form.elf_id)}</span> : <span className="text-xs text-muted-foreground">请先选择精灵</span>}
                </div>
                {[0, 1, 2, 3].map((slot) => (
                  <div key={slot} className="rounded-2xl border p-3">
                    <SkillSearchSelect label={`技能槽 ${slot + 1}`} value={form.skill_ids[slot]} elfId={form.elf_id} onChange={(id) => selectSkill(slot, id)} />
                    {form.skill_ids[slot] ? <Button className="mt-2 w-full" variant="ghost" size="sm" type="button" onClick={() => removeSkill(slot)}>清空该槽</Button> : null}
                  </div>
                ))}
              </div>
              <div>
                <label className="text-sm font-medium">配置名称</label>
                <Input value={form.build_name ?? ""} onChange={(e) => setForm({ ...form, build_name: e.target.value })} placeholder={selectedElf ? `${selectedElf.elf_name}配置` : "例如：PVP 常用配置"} />
              </div>
              <Textarea value={form.notes ?? ""} onChange={(e) => setForm({ ...form, notes: e.target.value })} placeholder="备注" />
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={Boolean(form.is_default)} onChange={(e) => setForm({ ...form, is_default: e.target.checked })} />
                设为该精灵默认配置
              </label>
              <div className="flex gap-2">
                <Button className="flex-1" type="submit" disabled={mutation.isPending}>{mutation.isPending ? "保存中..." : "保存配置"}</Button>
                <Button variant="outline" type="button" onClick={resetForm}>重置</Button>
              </div>
            </form>
          </CardContent>
        </Card>
      </div>
      <TeamPresetManager builds={builds.data ?? []} />
    </div>
  );
}

interface TeamPresetFormSlot {
  build_id: string;
  elf_id: string;
}

interface TeamPresetFormState {
  preset_name: string;
  side_usage: "self" | "enemy";
  source_type: "custom" | "popular";
  notes: string;
  slots: TeamPresetFormSlot[];
}

const emptyTeamSlots = (): TeamPresetFormSlot[] =>
  Array.from({ length: 6 }, () => ({ build_id: "", elf_id: "" }));

function TeamPresetManager({ builds }: { builds: PlayerElfBuildOut[] }) {
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const [editingPresetId, setEditingPresetId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<TeamPresetFormState>({
    preset_name: "",
    side_usage: "self",
    source_type: "custom",
    notes: "",
    slots: emptyTeamSlots(),
  });

  const teamPresets = useQuery({
    queryKey: ["team-presets", "build-page"],
    queryFn: () => api.teamPresets.list(),
  });

  const buildMap = useMemo(() => new Map(builds.map((build) => [build.build_id, build])), [builds]);

  const saveMutation = useMutation({
    mutationFn: () => {
      const payload = buildTeamPresetPayload(form);
      if (editingPresetId) return api.teamPresets.update(editingPresetId, payload);
      return api.teamPresets.create(payload);
    },
    onMutate: () => setError(null),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["team-presets"] });
      resetPresetForm();
    },
    onError: (mutationError) => {
      setError(mutationError instanceof Error ? mutationError.message : "保存配队失败");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (presetId: string) => api.teamPresets.delete(presetId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["team-presets"] });
      if (editingPresetId) resetPresetForm();
    },
  });

  const resetPresetForm = () => {
    setEditingPresetId(null);
    setError(null);
    setForm({
      preset_name: "",
      side_usage: "self",
      source_type: "custom",
      notes: "",
      slots: emptyTeamSlots(),
    });
  };

  const setSlot = (index: number, value: TeamPresetFormSlot) => {
    const next = [...form.slots];
    next[index] = value;
    setForm({ ...form, slots: next });
  };

  const editPreset = (preset: TeamPresetOut) => {
    const nextSlots = emptyTeamSlots();
    preset.slots.forEach((slot) => {
      if (slot.slot_index >= 0 && slot.slot_index < 6) {
        nextSlots[slot.slot_index] = {
          build_id: slot.build_id ?? "",
          elf_id: slot.elf_id,
        };
      }
    });
    setEditingPresetId(preset.preset_id);
    setError(null);
    setForm({
      preset_name: preset.preset_name,
      side_usage: preset.side_usage === "enemy" ? "enemy" : "self",
      source_type: preset.source_type,
      notes: preset.notes ?? "",
      slots: nextSlots,
    });
  };

  const requestDeletePreset = async (preset: TeamPresetOut) => {
    const confirmed = await confirm({
      title: "删除配队",
      description: `确认删除配队「${preset.preset_name}」？`,
      confirmText: "删除",
      danger: true,
    });
    if (!confirmed) return;
    deleteMutation.mutate(preset.preset_id);
  };

  const selfPresets = (teamPresets.data ?? []).filter((preset) => preset.side_usage !== "enemy");
  const enemyPresets = (teamPresets.data ?? []).filter((preset) => preset.side_usage !== "self");

  return (
    <Card>
      <CardHeader>
        <CardTitle>配队预设</CardTitle>
        <CardDescription>己方配队由已保存配置组成；敌方热门阵容可以只录入精灵种类，用于准备阶段快速填充。</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {error ? <div className="rounded-2xl border border-destructive/25 bg-destructive/10 px-4 py-3 text-sm text-destructive">{error}</div> : null}
        <div className="grid gap-6 lg:grid-cols-[1fr_520px]">
          <div className="space-y-3">
            <div className="grid gap-3 md:grid-cols-2">
              <PresetList
                title="己方配队"
                presets={selfPresets}
                onEdit={editPreset}
                onDelete={requestDeletePreset}
              />
              <PresetList
                title="敌方热门阵容"
                presets={enemyPresets}
                onEdit={editPreset}
                onDelete={requestDeletePreset}
              />
            </div>
          </div>

          <form
            className="space-y-4 rounded-2xl border bg-raised/60 p-4"
            onSubmit={(event) => {
              event.preventDefault();
              saveMutation.mutate();
            }}
          >
            <div className="flex items-center justify-between gap-3">
              <div className="font-semibold">{editingPresetId ? "编辑配队" : "新建配队"}</div>
              {editingPresetId ? <Badge variant="outline">{compactId(editingPresetId)}</Badge> : null}
            </div>
            <div>
              <label className="text-sm font-medium">配队名称</label>
              <Input
                value={form.preset_name}
                onChange={(event) => setForm({ ...form, preset_name: event.target.value })}
                placeholder="例如：常用火神队 / 热门帕尔队"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-sm font-medium">用途</label>
                <Select
                  value={form.side_usage}
                  onChange={(event) =>
                    setForm({
                      ...form,
                      side_usage: event.target.value === "enemy" ? "enemy" : "self",
                      slots: emptyTeamSlots(),
                    })
                  }
                >
                  <option value="self">己方配队</option>
                  <option value="enemy">敌方热门阵容</option>
                </Select>
              </div>
              <div>
                <label className="text-sm font-medium">来源</label>
                <Select
                  value={form.source_type}
                  onChange={(event) =>
                    setForm({ ...form, source_type: event.target.value === "popular" ? "popular" : "custom" })
                  }
                >
                  <option value="custom">自定义</option>
                  <option value="popular">热门队伍</option>
                </Select>
              </div>
            </div>
            <Textarea
              value={form.notes}
              onChange={(event) => setForm({ ...form, notes: event.target.value })}
              placeholder="备注"
            />
            <div className="grid gap-3">
              {form.slots.map((slot, index) => (
                <div key={index} className="rounded-2xl border p-3">
                  <div className="mb-2 text-sm font-medium">槽位 {index + 1}</div>
                  {form.side_usage === "self" ? (
                    <Select
                      value={slot.build_id}
                      onChange={(event) => {
                        const build = buildMap.get(event.target.value);
                        setSlot(index, {
                          build_id: event.target.value,
                          elf_id: build?.elf_id ?? "",
                        });
                      }}
                    >
                      <option value="">选择己方配置</option>
                      {builds.map((build) => (
                        <option key={build.build_id} value={build.build_id}>
                          {build.build_name || build.elf_name || compactId(build.elf_id)}
                        </option>
                      ))}
                    </Select>
                  ) : (
                    <ElfSearchSelect
                      label="敌方精灵"
                      value={slot.elf_id}
                      onChange={(id) => setSlot(index, { build_id: "", elf_id: id })}
                    />
                  )}
                </div>
              ))}
            </div>
            <div className="flex gap-2">
              <Button className="flex-1" type="submit" disabled={saveMutation.isPending || !form.preset_name.trim()}>
                {saveMutation.isPending ? "保存中..." : "保存配队"}
              </Button>
              <Button variant="outline" type="button" onClick={resetPresetForm}>重置</Button>
            </div>
          </form>
        </div>
      </CardContent>
    </Card>
  );
}

function PresetList({
  title,
  presets,
  onEdit,
  onDelete,
}: {
  title: string;
  presets: TeamPresetOut[];
  onEdit: (preset: TeamPresetOut) => void;
  onDelete: (preset: TeamPresetOut) => void;
}) {
  return (
    <div className="rounded-2xl border bg-raised/60 p-3">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="text-sm font-semibold">{title}</div>
        <Badge variant="outline">{presets.length}</Badge>
      </div>
      {presets.length === 0 ? <div className="text-sm text-muted-foreground">暂无配队。</div> : null}
      <div className="space-y-2">
        {presets.map((preset) => (
          <div key={preset.preset_id} className="rounded-xl border bg-raised/60 p-3 text-xs">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="truncate font-medium">{preset.preset_name}</div>
                <div className="mt-1 text-muted-foreground">
                  {preset.source_type === "popular" ? "热门队伍" : "自定义"} · {preset.slots.length} 只
                </div>
              </div>
              <div className="flex shrink-0 gap-2">
                <Button variant="outline" size="sm" type="button" onClick={() => onEdit(preset)}>编辑</Button>
                <Button variant="destructive" size="sm" type="button" onClick={() => onDelete(preset)}>删除</Button>
              </div>
            </div>
            <div className="mt-2 flex flex-wrap gap-1">
              {preset.slots.map((slot) => (
                <Badge key={slot.slot_id} variant="secondary">
                  {slot.slot_index + 1}. {slot.build_name || slot.elf_name || compactId(slot.elf_id)}
                </Badge>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function buildTeamPresetPayload(form: TeamPresetFormState): TeamPresetCreate {
  return {
    preset_name: form.preset_name.trim(),
    side_usage: form.side_usage,
    source_type: form.source_type,
    notes: form.notes.trim() || null,
    slots: form.slots
      .map((slot, index) => ({ ...slot, slot_index: index }))
      .filter((slot) => slot.elf_id)
      .map((slot) => ({
        slot_index: slot.slot_index,
        elf_id: slot.elf_id,
        build_id: slot.build_id || null,
      })),
  };
}
