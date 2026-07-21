import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertTriangle, Calculator, Crosshair, Shield, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import { AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { ElfSearchSelect, SkillSearchSelect } from "@/components/EntitySearchSelect";
import type {
  DamageCalculatorBattleOptionOut,
  DamageCalculatorModifierInput,
  DamageCalculatorPanelInput,
  DamageCalculatorParticipantInput,
  DamageCalculatorTalentInput,
  ElfDefinitionOut,
  NatureDefinitionOut,
  SkillDefinitionOut,
  StarfallComboCalculateInput,
  StarfallComboResultOut,
} from "@/types/api";
import {
  canonicalElementType,
  cn,
  compactId,
  elementTypeMatches,
  elementTypeNames,
  parseElementTypes,
  skillCategoryName,
  statName,
} from "@/lib/utils";

const statKeys = ["hp", "physical_attack", "physical_defense", "magic_attack", "magic_defense", "speed"] as const;
type StatKey = (typeof statKeys)[number];
type SideKey = "attacker" | "defender";
type ModifierKey = keyof ModifierForm;

interface ParticipantForm {
  elf_id: string;
  elf_name?: string | null;
  avatar?: string | null;
  element_types: string[];
  nature_id: string;
  talents: DamageCalculatorTalentInput;
  panel_stats: DamageCalculatorPanelInput | null;
  use_panel_stats: boolean;
  imported_nature_id: string;
  imported_talents: DamageCalculatorTalentInput | null;
}

interface ModifierForm {
  hit_count: string;
  base_power_override: string;
  power_multiplier: string;
  flat_power_bonus: string;
  stat_stage_multiplier: string;
  stab_multiplier: string;
  type_multiplier: string;
  weather_multiplier: string;
  unstable_multiplier: string;
  damage_reductions: string;
  starfall_type_multiplier: string;
  observed_damage_value: string;
  attacker_physical_attack_up_layers: string;
  attacker_physical_attack_down_layers: string;
  attacker_magic_attack_up_layers: string;
  attacker_magic_attack_down_layers: string;
  defender_physical_defense_up_layers: string;
  defender_physical_defense_down_layers: string;
  defender_magic_defense_up_layers: string;
  defender_magic_defense_down_layers: string;
  skill_power_up_layers: string;
  skill_power_down_layers: string;
}

const emptyTalents: DamageCalculatorTalentInput = {
  hp: 0,
  physical_attack: 0,
  physical_defense: 0,
  magic_attack: 0,
  magic_defense: 0,
  speed: 0,
};

const defaultPanel: DamageCalculatorPanelInput = {
  hp: 500,
  physical_attack: 100,
  physical_defense: 100,
  magic_attack: 100,
  magic_defense: 100,
  speed: 100,
};

const defaultModifiers: ModifierForm = {
  hit_count: "1",
  base_power_override: "",
  power_multiplier: "",
  flat_power_bonus: "",
  stat_stage_multiplier: "",
  stab_multiplier: "",
  type_multiplier: "",
  weather_multiplier: "",
  unstable_multiplier: "",
  damage_reductions: "",
  starfall_type_multiplier: "",
  observed_damage_value: "",
  attacker_physical_attack_up_layers: "",
  attacker_physical_attack_down_layers: "",
  attacker_magic_attack_up_layers: "",
  attacker_magic_attack_down_layers: "",
  defender_physical_defense_up_layers: "",
  defender_physical_defense_down_layers: "",
  defender_magic_defense_up_layers: "",
  defender_magic_defense_down_layers: "",
  skill_power_up_layers: "",
  skill_power_down_layers: "",
};

const emptyParticipant = (): ParticipantForm => ({
  elf_id: "",
  element_types: [],
  nature_id: "",
  talents: { ...emptyTalents },
  panel_stats: null,
  use_panel_stats: false,
  imported_nature_id: "",
  imported_talents: null,
});

function optionalNumber(value: string): number | null {
  if (!value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function optionalLayer(value: string): number {
  const parsed = optionalNumber(value);
  return parsed === null ? 0 : Math.max(0, Math.floor(parsed));
}

function clampInteger(value: string, min: number, max: number): number {
  const parsed = Math.floor(Number(value));
  if (!Number.isFinite(parsed)) return min;
  return Math.max(min, Math.min(max, parsed));
}

function parseReductionList(value: string): number[] {
  return value
    .split(/[,，\s]+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => {
      if (item.endsWith("%")) {
        const parsed = Number(item.slice(0, -1));
        return Number.isFinite(parsed) ? parsed / 100 : Number.NaN;
      }
      const parsed = Number(item);
      return parsed > 1 ? parsed / 100 : parsed;
    })
    .filter(Number.isFinite);
}

function hasAnyPositiveTalent(talents: DamageCalculatorTalentInput): boolean {
  return statKeys.some((key) => Number(talents[key] ?? 0) > 0);
}

function mainAttackStat(elf?: ElfDefinitionOut | null, negativeStat?: string | null): StatKey {
  const physical = elf?.base_physical_attack_talent ?? 0;
  const magic = elf?.base_magic_attack_talent ?? 0;
  if (negativeStat === "physical_attack") return "magic_attack";
  if (negativeStat === "magic_attack") return "physical_attack";
  return physical >= magic ? "physical_attack" : "magic_attack";
}

function strongerDefenseStat(elf?: ElfDefinitionOut | null, negativeStat?: string | null): StatKey {
  const physical = elf?.base_physical_defense_talent ?? 0;
  const magic = elf?.base_magic_defense_talent ?? 0;
  if (negativeStat === "physical_defense") return "magic_defense";
  if (negativeStat === "magic_defense") return "physical_defense";
  return physical >= magic ? "physical_defense" : "magic_defense";
}

function defaultTalentsForNature(
  nature: { positive_stat: string; negative_stat: string },
  elf?: ElfDefinitionOut | null,
): DamageCalculatorTalentInput {
  const talents: DamageCalculatorTalentInput = { ...emptyTalents, hp: 10 };
  const add = (key: StatKey) => {
    if (key !== nature.negative_stat) talents[key] = 10;
  };
  const mainAttack = mainAttackStat(elf, nature.negative_stat);
  const defense = strongerDefenseStat(elf, nature.negative_stat);

  if (nature.positive_stat === "hp") {
    if (nature.negative_stat === "physical_attack" || nature.negative_stat === "magic_attack") {
      add("physical_defense");
      add("magic_defense");
    } else if (nature.negative_stat === "physical_defense") {
      add("magic_defense");
      add(mainAttack);
    } else if (nature.negative_stat === "magic_defense") {
      add("physical_defense");
      add(mainAttack);
    } else {
      add(mainAttack);
      add(defense);
    }
  } else if (nature.positive_stat === "speed") {
    add("speed");
    add(mainAttack);
  } else if (nature.positive_stat === "physical_attack" || nature.positive_stat === "magic_attack") {
    add(nature.positive_stat as StatKey);
    add((elf?.base_speed_talent ?? 0) >= 110 ? "speed" : defense);
  } else if (nature.positive_stat === "physical_defense" || nature.positive_stat === "magic_defense") {
    add(nature.positive_stat as StatKey);
    add(mainAttack);
  } else {
    add(mainAttack);
    add((elf?.base_speed_talent ?? 0) >= 110 ? "speed" : defense);
  }

  return talents;
}

function computedStatStageMultiplier(form: ModifierForm, skillCategory?: string | null): number | null {
  const isMagicSkill = skillCategory === "magic";
  const attackUp = optionalLayer(isMagicSkill ? form.attacker_magic_attack_up_layers : form.attacker_physical_attack_up_layers) * 0.1;
  const attackDown = optionalLayer(isMagicSkill ? form.attacker_magic_attack_down_layers : form.attacker_physical_attack_down_layers) * 0.1;
  const defenseUp = optionalLayer(isMagicSkill ? form.defender_magic_defense_up_layers : form.defender_physical_defense_up_layers) * 0.1;
  const defenseDown = optionalLayer(isMagicSkill ? form.defender_magic_defense_down_layers : form.defender_physical_defense_down_layers) * 0.1;
  if (attackUp === 0 && attackDown === 0 && defenseUp === 0 && defenseDown === 0) return null;
  return (1 + attackUp + defenseDown) / (1 + attackDown + defenseUp);
}

function computedFlatPowerBonus(form: ModifierForm): number | null {
  const manualFlat = optionalNumber(form.flat_power_bonus) ?? 0;
  const layerFlat = (optionalLayer(form.skill_power_up_layers) - optionalLayer(form.skill_power_down_layers)) * 10;
  const total = manualFlat + layerFlat;
  if (total === 0 && !form.flat_power_bonus.trim() && layerFlat === 0) return null;
  return total;
}

function buildModifiers(form: ModifierForm, skillCategory?: string | null): DamageCalculatorModifierInput {
  const hitCount = optionalNumber(form.hit_count);
  const manualStatStage = optionalNumber(form.stat_stage_multiplier);
  return {
    hit_count: hitCount === null ? null : Math.max(1, Math.floor(hitCount)),
    base_power_override: optionalNumber(form.base_power_override),
    power_multiplier: optionalNumber(form.power_multiplier),
    flat_power_bonus: computedFlatPowerBonus(form),
    stat_stage_multiplier: manualStatStage ?? computedStatStageMultiplier(form, skillCategory),
    stab_multiplier: optionalNumber(form.stab_multiplier),
    type_multiplier: optionalNumber(form.type_multiplier),
    weather_multiplier: optionalNumber(form.weather_multiplier),
    unstable_multiplier: optionalNumber(form.unstable_multiplier),
    damage_reductions: parseReductionList(form.damage_reductions),
  };
}

function participantPayload(form: ParticipantForm): DamageCalculatorParticipantInput {
  return {
    elf_id: form.elf_id,
    nature_id: form.nature_id || null,
    individual_talent_distribution: form.talents,
    panel_stats: form.use_panel_stats ? form.panel_stats : null,
  };
}

function fillFromBattleOption(option: DamageCalculatorBattleOptionOut): ParticipantForm {
  const importedNatureId = option.nature_id ?? "";
  const importedTalents = { ...emptyTalents, ...(option.individual_talent_distribution ?? {}) };
  return {
    elf_id: option.elf_id,
    elf_name: option.elf_name,
    avatar: option.avatar,
    element_types: [],
    nature_id: importedNatureId,
    talents: importedTalents,
    panel_stats: option.panel_stats ?? null,
    use_panel_stats: Boolean(option.panel_stats),
    imported_nature_id: importedNatureId,
    imported_talents: importedTalents,
  };
}

function fillFromElf(
  elf: ElfDefinitionOut,
  current: ParticipantForm,
  natureOptions: NatureDefinitionOut[],
): ParticipantForm {
  const selectedNature = natureOptions.find((nature) => nature.nature_id === current.nature_id);
  return {
    ...current,
    elf_id: elf.elf_id,
    elf_name: elf.elf_name,
    avatar: elf.avatar,
    element_types: parseElementTypes(elf.element_types_json),
    talents: selectedNature && !hasAnyPositiveTalent(current.talents)
      ? defaultTalentsForNature(selectedNature, elf)
      : current.talents,
  };
}

function combineTypeMultipliers(values: number[]): number {
  if (values.length === 0) return 1;
  if (values.length === 1) return values[0];
  const [first, second] = values;
  const pair = new Set([first, second]);
  if (first === 2 && second === 2) return 3;
  if (first === 0.5 && second === 0.5) return 0.25;
  if (pair.has(2) && pair.has(0.5)) return 1;
  if (pair.has(2) && pair.has(1)) return 2;
  if (pair.has(0.5) && pair.has(1)) return 0.5;
  return 1;
}

function safeParseRecord(value?: string | null): Record<string, unknown> {
  if (!value) return {};
  try {
    const parsed = JSON.parse(value) as unknown;
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, unknown> : {};
  } catch {
    return {};
  }
}

function formatDamage(value?: number | null): string {
  return value === null || value === undefined ? "--" : String(value);
}

function formatPercent(value?: number | null): string {
  return value === null || value === undefined ? "--" : `${value.toFixed(2)}%`;
}

function panelText(panel?: DamageCalculatorPanelInput | null): string {
  if (!panel) return "按性格与资质计算";
  return `HP ${panel.hp} / 物攻 ${panel.physical_attack} / 物防 ${panel.physical_defense} / 魔攻 ${panel.magic_attack} / 魔防 ${panel.magic_defense} / 速度 ${panel.speed}`;
}

function talentSummary(talents: DamageCalculatorTalentInput): string {
  const items = statKeys.map((key) => ({ key, value: Number(talents[key] ?? 0) })).filter((item) => item.value > 0);
  if (items.length === 0) return "未点资质";
  return items.map((item) => `${statName(item.key)} ${item.value}`).join(" / ");
}

export function StarfallCalculatorPage() {
  const [attacker, setAttacker] = useState<ParticipantForm>(() => emptyParticipant());
  const [defender, setDefender] = useState<ParticipantForm>(() => emptyParticipant());
  const [triggerSkill, setTriggerSkill] = useState<SkillDefinitionOut | null>(null);
  const [starfallLayers, setStarfallLayers] = useState("3");
  const [modifiers, setModifiers] = useState<ModifierForm>({ ...defaultModifiers });
  const [manualModifierFields, setManualModifierFields] = useState<Partial<Record<ModifierKey, boolean>>>({});
  const [manualError, setManualError] = useState<string | null>(null);
  const [autoCalculate, setAutoCalculate] = useState(true);
  const lastSuggestedModifiers = useRef<Partial<ModifierForm>>({});

  const bootstrapQuery = useQuery({
    queryKey: ["damage-calculator", "starfall-bootstrap"],
    queryFn: () => api.damageCalculator.bootstrap(),
    retry: false,
  });
  const naturesQuery = useQuery({ queryKey: ["natures", "starfall-calculator"], queryFn: () => api.natures.list({ limit: 100 }) });
  const attackerDetail = useQuery({
    queryKey: ["elf", attacker.elf_id, "starfall-attacker"],
    queryFn: () => api.elves.get(attacker.elf_id),
    enabled: Boolean(attacker.elf_id),
  });
  const defenderDetail = useQuery({
    queryKey: ["elf", defender.elf_id, "starfall-defender"],
    queryFn: () => api.elves.get(defender.elf_id),
    enabled: Boolean(defender.elf_id),
  });
  const mutation = useMutation({ mutationFn: (payload: StarfallComboCalculateInput) => api.damageCalculator.starfallCombo(payload) });

  const natureOptions = naturesQuery.data ?? [];
  const attackerElf = attackerDetail.data ?? null;
  const defenderElf = defenderDetail.data ?? null;
  const attackerTypes = useMemo(
    () => attacker.element_types.length > 0 ? attacker.element_types : parseElementTypes(attackerElf?.element_types_json),
    [attacker.element_types, attackerElf?.element_types_json],
  );
  const defenderTypes = useMemo(
    () => defender.element_types.length > 0 ? defender.element_types : parseElementTypes(defenderElf?.element_types_json),
    [defender.element_types, defenderElf?.element_types_json],
  );
  const layers = clampInteger(starfallLayers, 0, 99);
  const result = mutation.data;
  const resultPercent = Math.max(0, Math.min(100, result?.damage_percent ?? 0));
  const latestBattle = bootstrapQuery.data?.latest_battle ?? null;
  const typeRuleMap = useMemo(() => {
    const map = new Map<string, number>();
    for (const rule of bootstrapQuery.data?.type_effectiveness_rules ?? []) {
      const attackType = canonicalElementType(rule.attack_element_type);
      const defenseType = canonicalElementType(rule.defense_element_type);
      if (attackType && defenseType) map.set(`${attackType}:${defenseType}`, rule.multiplier);
    }
    return map;
  }, [bootstrapQuery.data?.type_effectiveness_rules]);

  useEffect(() => {
    if (!triggerSkill) return;
    const triggerType = canonicalElementType(triggerSkill.element_type);
    const skillValues = defenderTypes.slice(0, 2).map((defenseType) => {
      const canonicalDefenseType = canonicalElementType(defenseType);
      return triggerType && canonicalDefenseType ? typeRuleMap.get(`${triggerType}:${canonicalDefenseType}`) ?? 1 : 1;
    });
    const starfallValues = defenderTypes.slice(0, 2).map((defenseType) => {
      const canonicalDefenseType = canonicalElementType(defenseType);
      return canonicalDefenseType ? typeRuleMap.get(`illusion:${canonicalDefenseType}`) ?? 1 : 1;
    });
    const hitRule = safeParseRecord(triggerSkill.hit_rule_json);
    const hitCount = hitRule.hit_count ?? hitRule.combo_count ?? hitRule.fixed_hit_count;
    const suggested: Partial<ModifierForm> = {
      stab_multiplier: attackerTypes.some((item) => elementTypeMatches(item, triggerSkill.element_type)) ? "1.25" : "1",
    };
    if (skillValues.length > 0 && typeRuleMap.size > 0) suggested.type_multiplier = String(combineTypeMultipliers(skillValues));
    if (starfallValues.length > 0 && typeRuleMap.size > 0) suggested.starfall_type_multiplier = String(combineTypeMultipliers(starfallValues));
    if (typeof hitCount === "number" && hitCount >= 1) suggested.hit_count = String(hitCount);
    setModifiers((prev) => {
      const next = { ...prev };
      for (const key of Object.keys(suggested) as ModifierKey[]) {
        const previousSuggested = lastSuggestedModifiers.current[key];
        if (!manualModifierFields[key] || !next[key] || next[key] === previousSuggested) next[key] = suggested[key] ?? "";
      }
      return next;
    });
    lastSuggestedModifiers.current = suggested;
  }, [attackerTypes, defenderTypes, manualModifierFields, triggerSkill, typeRuleMap]);

  const setPanelValue = (side: SideKey, key: StatKey, rawValue: string) => {
    const parsed = Math.max(1, Math.floor(Number(rawValue) || 1));
    const setter = side === "attacker" ? setAttacker : setDefender;
    setter((current) => ({ ...current, panel_stats: { ...(current.panel_stats ?? defaultPanel), [key]: parsed } }));
  };
  const updateTalent = (side: SideKey, key: StatKey, value: number) => {
    const setter = side === "attacker" ? setAttacker : setDefender;
    setter((current) => ({ ...current, talents: { ...current.talents, [key]: value } }));
  };
  const updateNature = (side: SideKey, natureId: string) => {
    const setter = side === "attacker" ? setAttacker : setDefender;
    const elf = side === "attacker" ? attackerElf : defenderElf;
    const nature = natureOptions.find((item) => item.nature_id === natureId);
    setter((current) => ({ ...current, nature_id: natureId, talents: nature ? defaultTalentsForNature(nature, elf) : current.talents }));
  };
  const togglePanelStats = (side: SideKey, enabled: boolean) => {
    const setter = side === "attacker" ? setAttacker : setDefender;
    setter((current) => ({ ...current, use_panel_stats: enabled, panel_stats: enabled ? current.panel_stats ?? { ...defaultPanel } : current.panel_stats }));
  };
  const updateModifier = (key: ModifierKey, value: string) => {
    setManualModifierFields((current) => ({ ...current, [key]: true }));
    setModifiers((current) => ({ ...current, [key]: value }));
  };

  const participantValidationError = (participant: ParticipantForm, label: string): string | null => {
    if (!participant.elf_id) return `${label}：请选择精灵`;
    if (participant.use_panel_stats) return participant.panel_stats ? null : `${label}：请填写手动面板，或关闭“使用面板”`;
    if (!participant.nature_id) return `${label}：请选择性格`;
    if (!hasAnyPositiveTalent(participant.talents)) return `${label}：请选择至少一项资质`;
    return null;
  };
  const validationError = useMemo(() => {
    const attackerError = participantValidationError(attacker, "我方");
    if (attackerError) return attackerError;
    const defenderError = participantValidationError(defender, "敌方");
    if (defenderError) return defenderError;
    if (!triggerSkill?.skill_id) return "请选择触发星陨的技能";
    return null;
  }, [attacker, defender, triggerSkill?.skill_id]);
  const payload = useMemo<StarfallComboCalculateInput | null>(() => {
    if (validationError || !triggerSkill?.skill_id) return null;
    return {
      attacker: participantPayload(attacker),
      defender: participantPayload(defender),
      trigger_skill_id: triggerSkill.skill_id,
      starfall_layers: layers,
      modifiers: buildModifiers(modifiers, triggerSkill.skill_category),
      starfall_type_multiplier: optionalNumber(modifiers.starfall_type_multiplier),
      observed_damage_value: optionalNumber(modifiers.observed_damage_value),
    };
  }, [attacker, defender, layers, modifiers, triggerSkill, validationError]);
  useEffect(() => {
    if (!autoCalculate || !payload) return;
    setManualError(null);
    const timer = window.setTimeout(() => mutation.mutate(payload), 220);
    return () => window.clearTimeout(timer);
  }, [autoCalculate, payload, mutation.mutate]);
  const calculateNow = () => {
    if (!payload) {
      setManualError(validationError ?? "请先补齐计算条件");
      return;
    }
    setManualError(null);
    mutation.mutate(payload);
  };

  return (
    <div className="space-y-6">
      <section className="relative overflow-hidden rounded-2xl border border-primary/20 bg-card/80 p-6 shadow-glow-sm">
        <div className="absolute -left-12 top-10 h-32 w-32 rounded-full bg-info/15 blur-3xl" />
        <div className="absolute -right-16 -top-16 h-44 w-44 rounded-full bg-primary/15 blur-3xl" />
        <div className="relative flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="mb-2 flex items-center gap-2">
              <Sparkles className="h-5 w-5 text-primary" />
              <Badge variant="outline">工具包 / 星陨伤害计算器</Badge>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-2xl font-semibold tracking-tight">星陨伤害计算器</h1>
              <Button
                type="button"
                size="sm"
                variant={autoCalculate ? "secondary" : "outline"}
                onClick={() => setAutoCalculate((value) => !value)}
              >
                自动计算：{autoCalculate ? "开" : "关"}
              </Button>
            </div>
          </div>
          <div className="flex flex-col items-end gap-2">
            <Button type="button" onClick={calculateNow} disabled={mutation.isPending}>
              <Calculator className="h-4 w-4" />
              {mutation.isPending ? "计算中..." : "立即计算"}
            </Button>
            <span className="text-xs text-muted-foreground">
              {payload ? (autoCalculate ? "拖动层数会自动刷新" : "自动计算已关闭") : validationError ?? "等待输入"}
            </span>
          </div>
        </div>
      </section>

      {latestBattle ? (
        <Card>
          <CardHeader>
            <CardTitle>最近战斗快捷导入</CardTitle>
            <CardDescription>导入后默认使用战斗面板；也可以关闭面板，改用性格和资质重新计算。</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 lg:grid-cols-2">
            <BattleImportGroup
              title="我方队伍"
              options={latestBattle.self_lineup}
              defaultTargetLabel="导入到我方"
              onDefaultImport={(option) => setAttacker(fillFromBattleOption(option))}
              onOtherImport={(option) => setDefender(fillFromBattleOption(option))}
              otherTargetLabel="放到敌方"
            />
            <BattleImportGroup
              title="敌方队伍"
              options={latestBattle.enemy_lineup}
              defaultTargetLabel="导入到敌方"
              onDefaultImport={(option) => setDefender(fillFromBattleOption(option))}
              onOtherImport={(option) => setAttacker(fillFromBattleOption(option))}
              otherTargetLabel="放到我方"
            />
          </CardContent>
        </Card>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-[minmax(280px,1fr)_minmax(280px,1fr)_minmax(320px,0.8fr)]">
        <ParticipantPanel
          side="self"
          title="我方精灵"
          icon={<Crosshair className="h-4 w-4 text-self" />}
          participant={attacker}
          elfDetail={attackerElf}
          natureOptions={natureOptions}
          onElfChange={(elf) => setAttacker((current) => fillFromElf(elf, current, natureOptions))}
          onNatureChange={(value) => updateNature("attacker", value)}
          onTalentChange={(key, value) => updateTalent("attacker", key, value)}
          onPanelToggle={(value) => togglePanelStats("attacker", value)}
          onPanelChange={(key, value) => setPanelValue("attacker", key, value)}
        />
        <ParticipantPanel
          side="enemy"
          title="敌方精灵"
          icon={<Shield className="h-4 w-4 text-enemy" />}
          participant={defender}
          elfDetail={defenderElf}
          natureOptions={natureOptions}
          onElfChange={(elf) => setDefender((current) => fillFromElf(elf, current, natureOptions))}
          onNatureChange={(value) => updateNature("defender", value)}
          onTalentChange={(key, value) => updateTalent("defender", key, value)}
          onPanelToggle={(value) => togglePanelStats("defender", value)}
          onPanelChange={(key, value) => setPanelValue("defender", key, value)}
        />
        <StarfallControlPanel
          layers={layers}
          rawLayers={starfallLayers}
          setRawLayers={setStarfallLayers}
          result={result}
          resultPercent={resultPercent}
          pending={mutation.isPending}
        />
      </div>

      <TriggerParameterPanel
        triggerSkill={triggerSkill}
        setTriggerSkill={setTriggerSkill}
        attackerElfId={attacker.elf_id}
        modifiers={modifiers}
        updateModifier={updateModifier}
      />

      {manualError || mutation.error ? (
        <div className="flex items-start gap-2 rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
          <AlertTriangle className="mt-0.5 h-4 w-4" />
          <span>{manualError ?? (mutation.error instanceof Error ? mutation.error.message : "计算失败")}</span>
        </div>
      ) : null}

      {result ? (
        <Card>
          <CardHeader>
            <CardTitle>公式解释链</CardTitle>
            <CardDescription>保留触发技能与星陨印记两段计算的关键输入，方便后续核验。</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 text-sm lg:grid-cols-2">
            <FormulaBlock title="触发技能伤害" data={result.skill_result.explanation} />
            <FormulaBlock title="星陨印记伤害" data={result.starfall_result.explanation} />
            <ResultItem label="我方面板" value={panelText(result.attacker.panel_stats)} />
            <ResultItem label="敌方面板" value={panelText(result.defender.panel_stats)} />
            {result.unknown_factors.length > 0 ? <ResultItem label="未知因素" value={result.unknown_factors.join("，")} /> : null}
            {result.missing_parts.length > 0 ? <ResultItem label="缺失输入" value={result.missing_parts.join("，")} /> : null}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

function BattleImportGroup({
  title,
  options,
  defaultTargetLabel,
  onDefaultImport,
  otherTargetLabel,
  onOtherImport,
}: {
  title: string;
  options: DamageCalculatorBattleOptionOut[];
  defaultTargetLabel: string;
  onDefaultImport: (option: DamageCalculatorBattleOptionOut) => void;
  otherTargetLabel: string;
  onOtherImport: (option: DamageCalculatorBattleOptionOut) => void;
}) {
  return (
    <details className="rounded-2xl border border-border/70 bg-raised/40 p-3">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-semibold [&::-webkit-details-marker]:hidden">
        <span>{title}</span>
        <Badge variant="secondary">{options.length} 只</Badge>
      </summary>
      <div className="mt-3 space-y-2">
        {options.length > 0 ? options.map((option) => (
          <div key={`${title}-${option.elf_id}`} className="flex flex-wrap items-center gap-2 rounded-xl border border-border/70 bg-card/60 p-2">
            <AvatarImage src={option.avatar} alt={option.elf_name} fallback={option.elf_name} className="h-8 w-8" />
            <span className="min-w-28 flex-1 text-sm">{option.elf_name}</span>
            {option.nature_name ? <Badge variant="secondary">{option.nature_name}</Badge> : null}
            {option.panel_stats ? <Badge variant="outline">面板</Badge> : null}
            <Button type="button" size="sm" variant="secondary" onClick={() => onDefaultImport(option)}>
              {defaultTargetLabel}
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => onOtherImport(option)}>
              {otherTargetLabel}
            </Button>
          </div>
        )) : (
          <div className="rounded-xl border border-border/60 bg-card/50 px-3 py-2 text-xs text-muted-foreground">
            最近战斗中没有记录该队伍。
          </div>
        )}
      </div>
    </details>
  );
}

function ParticipantPanel({
  title,
  icon,
  side,
  participant,
  elfDetail,
  natureOptions,
  onElfChange,
  onNatureChange,
  onTalentChange,
  onPanelToggle,
  onPanelChange,
}: {
  title: string;
  icon: ReactNode;
  side: "self" | "enemy";
  participant: ParticipantForm;
  elfDetail?: ElfDefinitionOut | null;
  natureOptions: NatureDefinitionOut[];
  onElfChange: (elf: ElfDefinitionOut) => void;
  onNatureChange: (natureId: string) => void;
  onTalentChange: (key: StatKey, value: number) => void;
  onPanelToggle: (enabled: boolean) => void;
  onPanelChange: (key: StatKey, value: string) => void;
}) {
  const sideClass = side === "self" ? "border-self/30" : "border-enemy/30";
  const glowClass = side === "self" ? "bg-self/10" : "bg-enemy/10";
  const elementTypes = participant.element_types.length > 0 ? participant.element_types : parseElementTypes(elfDetail?.element_types_json);
  const selectedNature = natureOptions.find((nature) => nature.nature_id === participant.nature_id);
  return (
    <Card className={cn("overflow-hidden", sideClass)}>
      <CardHeader className="p-4 pb-2">
        <CardTitle className="flex items-center gap-2">{icon}{title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 p-4 pt-1">
        <div className={cn("rounded-2xl border border-border/70 p-3", glowClass)}>
          <div className="mb-2 flex items-center gap-3">
            <AvatarImage
              src={participant.avatar ?? elfDetail?.avatar}
              alt={participant.elf_name ?? elfDetail?.elf_name ?? participant.elf_id}
              fallback={participant.elf_name ?? elfDetail?.elf_name ?? "?"}
              className={cn("h-12 w-12 rounded-xl", side === "self" && "-scale-x-100")}
            />
            <div className="min-w-0">
              <div className="truncate text-base font-semibold">{participant.elf_name ?? elfDetail?.elf_name ?? "未选择精灵"}</div>
              <div className="truncate text-xs text-muted-foreground">{participant.elf_id ? compactId(participant.elf_id) : "从本地数据库搜索"}</div>
              <div className="mt-1 text-xs text-muted-foreground">{elementTypeNames(elementTypes)}</div>
            </div>
          </div>
          <ElfSearchSelect label="精灵" value={participant.elf_id} resultsMode="focus" onChange={(_, elf) => onElfChange(elf)} />
        </div>

        <div className="rounded-2xl border border-border/70 bg-raised/40 p-3">
          <label className="flex items-center justify-between gap-3 text-sm">
            <span>
              <span className="font-medium">使用面板值</span>
            </span>
            <input type="checkbox" checked={participant.use_panel_stats} onChange={(event) => onPanelToggle(event.target.checked)} className="h-4 w-4 accent-primary" />
          </label>
          {participant.imported_nature_id || participant.imported_talents ? (
            <div className="mt-2 text-xs text-muted-foreground">
              已导入：{participant.imported_nature_id || "未知性格"} · {participant.imported_talents ? talentSummary(participant.imported_talents) : "无资质"}
            </div>
          ) : null}
        </div>

        {!participant.use_panel_stats ? (
          <div className="space-y-3 rounded-2xl border border-border/70 bg-raised/40 p-3">
            <label className="block space-y-1.5 text-xs font-medium text-muted-foreground">
              <span>性格</span>
              <Select value={participant.nature_id} onChange={(event) => onNatureChange(event.target.value)}>
                <option value="">请选择性格</option>
                {natureOptions.map((nature) => (
                  <option key={nature.nature_id} value={nature.nature_id}>
                    {nature.nature_name}（{statName(nature.positive_stat)}+ / {statName(nature.negative_stat)}-）
                  </option>
                ))}
              </Select>
            </label>
            {selectedNature ? (
              <div className="rounded-xl border border-primary/15 bg-primary/5 px-3 py-2 text-xs text-muted-foreground">
                当前性格：{selectedNature.nature_name}，{statName(selectedNature.positive_stat)} × {selectedNature.positive_multiplier}，{statName(selectedNature.negative_stat)} × {selectedNature.negative_multiplier}
              </div>
            ) : null}
            <div className="grid grid-cols-2 gap-3 2xl:grid-cols-3">
              {statKeys.map((key) => (
                <TalentSelect key={key} label={`${statName(key)}资质`} value={Number(participant.talents[key] ?? 0)} onChange={(value) => onTalentChange(key, Math.max(0, Math.min(10, Number(value) || 0)))} />
              ))}
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-3 rounded-2xl border border-border/70 bg-raised/40 p-3 2xl:grid-cols-3">
            {statKeys.map((key) => (
              <LabeledInput key={key} label={statName(key)} value={String((participant.panel_stats ?? defaultPanel)[key])} type="number" min={1} onChange={(value) => onPanelChange(key, value)} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function StarfallControlPanel({
  layers,
  rawLayers,
  setRawLayers,
  result,
  resultPercent,
  pending,
}: {
  layers: number;
  rawLayers: string;
  setRawLayers: (value: string) => void;
  result?: StarfallComboResultOut;
  resultPercent: number;
  pending: boolean;
}) {
  return (
    <div className="space-y-4">
      <Card className="overflow-hidden border-primary/30 bg-primary/5">
        <CardHeader>
          <CardTitle className="flex items-center justify-between gap-2"><span>星陨层数</span><Badge variant="secondary">{layers} 层</Badge></CardTitle>
          <CardDescription>仅保留滑条与精确输入；拖动后结果会自动跟随刷新。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <input type="range" min={0} max={99} value={layers} onChange={(event) => setRawLayers(event.target.value)} className="w-full accent-primary" />
          <div className="grid grid-cols-3 gap-2 text-xs text-muted-foreground"><span>0</span><span className="text-center">50</span><span className="text-right">99</span></div>
          <LabeledInput label="层数精确输入" value={rawLayers} onChange={setRawLayers} type="number" min={0} max={99} />
        </CardContent>
      </Card>

      <Card className="border-primary/30">
        <CardHeader className="text-center">
          <CardTitle>伤害结果</CardTitle>
          <CardDescription>{pending ? "自动计算中..." : "精确数值与敌方最大 HP 百分比。"}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="relative mx-auto flex h-48 w-48 items-center justify-center">
            <svg className="absolute inset-0 h-full w-full -rotate-90" viewBox="0 0 100 100">
              <circle cx="50" cy="50" r="42" fill="none" stroke="currentColor" strokeWidth="7" className="text-muted/60" />
              <circle cx="50" cy="50" r="42" fill="none" stroke="currentColor" strokeWidth="7" strokeLinecap="round" strokeDasharray={`${resultPercent * 2.6389} 263.89`} className="text-primary drop-shadow transition-[stroke-dasharray] duration-300 ease-out" />
            </svg>
            <div className="relative text-center transition-opacity duration-200">
              <div className="font-num text-4xl font-semibold text-primary">{formatDamage(result?.total_damage_value)}</div>
              <div className="mt-1 font-num text-lg text-muted-foreground">{formatPercent(result?.damage_percent)}</div>
              <div className="mt-1 text-xs text-muted-foreground">总伤害</div>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3 text-sm">
            <ResultItem label="技能伤害" value={formatDamage(result?.skill_damage_value)} />
            <ResultItem label="星陨伤害" value={formatDamage(result?.starfall_damage_value)} />
            <ResultItem label="剩余 HP" value={formatDamage(result?.remaining_hp)} />
            <ResultItem label="击杀判断" value={result ? (result.is_kill ? "可击杀" : "未击杀") : "--"} />
            {result?.observed_comparison ? <ResultItem label="实战偏差" value={`${result.observed_comparison.delta_value ?? "--"}`} /> : null}
            {result ? <ResultItem label="置信度" value={String(result.confidence)} /> : null}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function TriggerParameterPanel({
  triggerSkill,
  setTriggerSkill,
  attackerElfId,
  modifiers,
  updateModifier,
}: {
  triggerSkill: SkillDefinitionOut | null;
  setTriggerSkill: (skill: SkillDefinitionOut) => void;
  attackerElfId: string;
  modifiers: ModifierForm;
  updateModifier: (key: ModifierKey, value: string) => void;
}) {
  const statStagePreview = optionalNumber(modifiers.stat_stage_multiplier) ?? computedStatStageMultiplier(modifiers, triggerSkill?.skill_category);
  const flatPowerPreview = computedFlatPowerBonus(modifiers);
  return (
    <Card>
      <CardHeader>
        <CardTitle>触发与参数</CardTitle>
        <CardDescription>先计算触发技能伤害，再按层数计算星陨印记伤害。</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-4 xl:grid-cols-[minmax(280px,0.7fr)_minmax(0,1.3fr)]">
          <div className="space-y-3">
            <SkillSearchSelect label="触发技能" value={triggerSkill?.skill_id} elfId={attackerElfId || undefined} resultsMode="focus" onChange={(_, skill) => setTriggerSkill(skill)} />
            {triggerSkill ? (
              <div className="rounded-xl border border-border/60 bg-raised/40 p-3 text-xs text-muted-foreground">
                {triggerSkill.skill_name} / {skillCategoryName(triggerSkill.skill_category)} / 威力 {triggerSkill.base_power ?? "--"} / {triggerSkill.element_type}
                {canonicalElementType(triggerSkill.element_type) === "illusion" ? <div className="mt-1 text-warning">幻系技能不会触发额外星陨伤害，后端会按规则返回。</div> : null}
              </div>
            ) : null}
          </div>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
            <LabeledInput label="连击段数" value={modifiers.hit_count} type="number" min={1} onChange={(value) => updateModifier("hit_count", value)} />
            <LabeledInput label="技能威力覆盖" value={modifiers.base_power_override} placeholder="留空" onChange={(value) => updateModifier("base_power_override", value)} />
            <LabeledInput label="技能威力倍率" value={modifiers.power_multiplier} placeholder="默认 1" onChange={(value) => updateModifier("power_multiplier", value)} />
            <LabeledInput label="固定威力修正" value={modifiers.flat_power_bonus} placeholder="可留空" onChange={(value) => updateModifier("flat_power_bonus", value)} />
            <LabeledInput label="本系倍率" value={modifiers.stab_multiplier} placeholder="自动建议" onChange={(value) => updateModifier("stab_multiplier", value)} />
            <LabeledInput label="技能克制倍率" value={modifiers.type_multiplier} placeholder="自动建议" onChange={(value) => updateModifier("type_multiplier", value)} />
            <LabeledInput label="星陨幻系倍率" value={modifiers.starfall_type_multiplier} placeholder="自动建议" onChange={(value) => updateModifier("starfall_type_multiplier", value)} />
            <LabeledInput label="天气倍率" value={modifiers.weather_multiplier} placeholder="默认 1" onChange={(value) => updateModifier("weather_multiplier", value)} />
            <LabeledInput label="能力倍率" value={modifiers.stat_stage_multiplier} placeholder="可手填覆盖" onChange={(value) => updateModifier("stat_stage_multiplier", value)} />
            <LabeledInput label="额外倍率" value={modifiers.unstable_multiplier} placeholder="默认 1" onChange={(value) => updateModifier("unstable_multiplier", value)} />
          </div>
        </div>
        <details className="rounded-xl border border-border/60 bg-raised/40 p-3">
          <summary className="cursor-pointer text-sm font-medium">层级快捷修正</summary>
          <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <LabeledInput label="我方物攻↑" value={modifiers.attacker_physical_attack_up_layers} type="number" min={0} onChange={(value) => updateModifier("attacker_physical_attack_up_layers", value)} />
            <LabeledInput label="我方物攻↓" value={modifiers.attacker_physical_attack_down_layers} type="number" min={0} onChange={(value) => updateModifier("attacker_physical_attack_down_layers", value)} />
            <LabeledInput label="我方魔攻↑" value={modifiers.attacker_magic_attack_up_layers} type="number" min={0} onChange={(value) => updateModifier("attacker_magic_attack_up_layers", value)} />
            <LabeledInput label="我方魔攻↓" value={modifiers.attacker_magic_attack_down_layers} type="number" min={0} onChange={(value) => updateModifier("attacker_magic_attack_down_layers", value)} />
            <LabeledInput label="敌方物防↑" value={modifiers.defender_physical_defense_up_layers} type="number" min={0} onChange={(value) => updateModifier("defender_physical_defense_up_layers", value)} />
            <LabeledInput label="敌方物防↓" value={modifiers.defender_physical_defense_down_layers} type="number" min={0} onChange={(value) => updateModifier("defender_physical_defense_down_layers", value)} />
            <LabeledInput label="敌方魔防↑" value={modifiers.defender_magic_defense_up_layers} type="number" min={0} onChange={(value) => updateModifier("defender_magic_defense_up_layers", value)} />
            <LabeledInput label="敌方魔防↓" value={modifiers.defender_magic_defense_down_layers} type="number" min={0} onChange={(value) => updateModifier("defender_magic_defense_down_layers", value)} />
            <LabeledInput label="技能威力↑层" value={modifiers.skill_power_up_layers} type="number" min={0} onChange={(value) => updateModifier("skill_power_up_layers", value)} />
            <LabeledInput label="技能威力↓层" value={modifiers.skill_power_down_layers} type="number" min={0} onChange={(value) => updateModifier("skill_power_down_layers", value)} />
          </div>
          <div className="mt-3 grid gap-2 text-xs text-muted-foreground sm:grid-cols-2">
            <span>能力倍率预览：{statStagePreview === null ? "未应用" : statStagePreview.toFixed(4)}</span>
            <span>固定威力修正预览：{flatPowerPreview === null ? "未应用" : flatPowerPreview}</span>
          </div>
        </details>
        <div className="grid gap-3 lg:grid-cols-2">
          <LabeledInput label="减伤列表" value={modifiers.damage_reductions} placeholder="例如 25% 或 0.25,0.5" onChange={(value) => updateModifier("damage_reductions", value)} />
          <LabeledInput label="实战总伤害" value={modifiers.observed_damage_value} placeholder="可选，用于偏差展示" onChange={(value) => updateModifier("observed_damage_value", value)} />
        </div>
      </CardContent>
    </Card>
  );
}

function LabeledInput({
  label,
  value,
  onChange,
  className,
  ...props
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  className?: string;
} & Omit<React.InputHTMLAttributes<HTMLInputElement>, "value" | "onChange">) {
  return (
    <label className={cn("space-y-1.5 text-xs font-medium text-muted-foreground", className)}>
      <span>{label}</span>
      <Input value={value} onChange={(event) => onChange(event.target.value)} {...props} />
    </label>
  );
}

function TalentSelect({ label, value, onChange }: { label: string; value: number; onChange: (value: string) => void }) {
  return (
    <label className="block space-y-1.5 text-xs font-medium text-muted-foreground">
      <span>{label}</span>
      <Select value={String(value)} onChange={(event) => onChange(event.target.value)}>
        <option value="0">不点</option>
        {[7, 8, 9, 10].map((item) => <option key={item} value={item}>{item}</option>)}
      </Select>
    </label>
  );
}

function ResultItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border/60 bg-raised/40 p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 break-words font-medium">{value}</div>
    </div>
  );
}

function FormulaBlock({ title, data }: { title: string; data: Record<string, unknown> }) {
  const rows = Object.entries(data).filter(([key]) => [
    "display_power",
    "single_damage",
    "hit_count",
    "total_damage",
    "starfall_power",
    "type_multiplier",
    "reduction_product",
    "final_damage",
    "trigger_skill_element_type",
    "trigger_skill_category",
  ].includes(key));
  return (
    <div className="rounded-xl border border-border/60 bg-raised/40 p-3">
      <div className="mb-2 text-xs font-semibold text-muted-foreground">{title}</div>
      {rows.length > 0 ? (
        <div className="grid gap-2 sm:grid-cols-2">
          {rows.map(([key, value]) => (
            <div key={key} className="flex items-center justify-between gap-3 rounded-lg bg-background/50 px-2 py-1 text-xs">
              <span className="text-muted-foreground">{key}</span>
              <span className="font-medium">{String(value)}</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-xs text-muted-foreground">暂无可展示的公式细节。</div>
      )}
    </div>
  );
}
