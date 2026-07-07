import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Calculator, RotateCcw } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { AvatarImage } from "@/components/ui/avatar";
import { ElfSearchSelect, SkillSearchSelect } from "@/components/EntitySearchSelect";
import type {
  DamageCalculatorBattleOptionOut,
  DamageCalculatorCalculateInput,
  DamageCalculatorInferDefenderBatchInput,
  DamageCalculatorInferDefenderBatchOut,
  DamageCalculatorInferDefenderInput,
  DamageCalculatorInferDefenderOut,
  DamageCalculatorInferDefenderSampleInput,
  DamageCalculatorModifierInput,
  DamageCalculatorPanelInput,
  DamageCalculatorTalentInput,
  ElfDefinitionOut,
  PlayerElfBuildOut,
  SkillDefinitionOut,
} from "@/types/api";
import { canonicalElementType, compactId, elementTypeMatches, elementTypeNames, parseElementTypes, skillCategoryName, statName } from "@/lib/utils";

const statKeys = ["hp", "physical_attack", "physical_defense", "magic_attack", "magic_defense", "speed"] as const;

type StatKey = (typeof statKeys)[number];
type CandidateMode = "focused" | "default_templates";
type CalculatorMode = "calculate" | "infer";

interface ParticipantForm {
  elf_id: string;
  nature_id: string;
  talents: DamageCalculatorTalentInput;
  panel_stats: DamageCalculatorPanelInput | null;
  use_panel_stats: boolean;
}

interface ModifierForm {
  weather_multiplier: string;
  power_multiplier: string;
  flat_power_bonus: string;
  stat_stage_multiplier: string;
  stab_multiplier: string;
  type_multiplier: string;
  unstable_multiplier: string;
  damage_reductions: string;
  hit_count: string;
  defender_hp_percent: string;
  condition_flags_json: string;
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

const emptyParticipant = (): ParticipantForm => ({
  elf_id: "",
  nature_id: "",
  talents: { ...emptyTalents },
  panel_stats: null,
  use_panel_stats: false,
});

const defaultModifiers: ModifierForm = {
  weather_multiplier: "",
  power_multiplier: "",
  flat_power_bonus: "",
  stat_stage_multiplier: "",
  stab_multiplier: "",
  type_multiplier: "",
  unstable_multiplier: "",
  damage_reductions: "",
  hit_count: "",
  defender_hp_percent: "",
  condition_flags_json: "",
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

function optionalNumber(value: string): number | null {
  if (!value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function parseReductionList(value: string): number[] {
  return value
    .split(/[，,\s]+/)
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

function optionalLayer(value: string): number {
  const parsed = optionalNumber(value);
  return parsed === null ? 0 : Math.max(0, Math.floor(parsed));
}

function computedStatStageMultiplier(
  form: ModifierForm,
  skillCategory?: string | null,
): number | null {
  const isMagicSkill = skillCategory === "magic";
  const attackUp = optionalLayer(
    isMagicSkill ? form.attacker_magic_attack_up_layers : form.attacker_physical_attack_up_layers,
  ) * 0.1;
  const attackDown = optionalLayer(
    isMagicSkill ? form.attacker_magic_attack_down_layers : form.attacker_physical_attack_down_layers,
  ) * 0.1;
  const defenseUp = optionalLayer(
    isMagicSkill ? form.defender_magic_defense_up_layers : form.defender_physical_defense_up_layers,
  ) * 0.1;
  const defenseDown = optionalLayer(
    isMagicSkill ? form.defender_magic_defense_down_layers : form.defender_physical_defense_down_layers,
  ) * 0.1;
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

function parseConditionFlags(value: string): Record<string, boolean> {
  if (!value.trim()) return {};
  const parsed = JSON.parse(value) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("条件标记必须是 JSON 对象，例如 {\"self_switched_this_turn\": true}");
  }
  return Object.fromEntries(
    Object.entries(parsed).filter((entry): entry is [string, boolean] => typeof entry[1] === "boolean"),
  );
}

function buildModifiers(
  form: ModifierForm,
  skillCategory?: string | null,
): DamageCalculatorModifierInput {
  const hitCount = optionalNumber(form.hit_count);
  const manualStatStage = optionalNumber(form.stat_stage_multiplier);
  const statStageMultiplier = manualStatStage ?? computedStatStageMultiplier(form, skillCategory);
  return {
    weather_multiplier: optionalNumber(form.weather_multiplier),
    power_multiplier: optionalNumber(form.power_multiplier),
    flat_power_bonus: computedFlatPowerBonus(form),
    stat_stage_multiplier: statStageMultiplier,
    stab_multiplier: optionalNumber(form.stab_multiplier),
    type_multiplier: optionalNumber(form.type_multiplier),
    unstable_multiplier: optionalNumber(form.unstable_multiplier),
    damage_reductions: parseReductionList(form.damage_reductions),
    hit_count: hitCount === null ? null : Math.max(1, Math.floor(hitCount)),
    defender_hp_percent: optionalNumber(form.defender_hp_percent),
    condition_flags: parseConditionFlags(form.condition_flags_json),
  };
}

function panelText(panel?: DamageCalculatorPanelInput | null) {
  if (!panel) return "无面板";
  return `HP ${panel.hp} / 物攻 ${panel.physical_attack} / 物防 ${panel.physical_defense} / 魔攻 ${panel.magic_attack} / 魔防 ${panel.magic_defense} / 速度 ${panel.speed}`;
}

function participantPayload(form: ParticipantForm) {
  return {
    elf_id: form.elf_id,
    nature_id: form.nature_id || null,
    individual_talent_distribution: form.talents,
    panel_stats: form.use_panel_stats ? form.panel_stats : null,
  };
}

function fillFromBattleOption(option: DamageCalculatorBattleOptionOut): ParticipantForm {
  return {
    elf_id: option.elf_id,
    nature_id: option.nature_id ?? "",
    talents: { ...emptyTalents, ...(option.individual_talent_distribution ?? {}) },
    panel_stats: option.panel_stats ?? null,
    use_panel_stats: Boolean(option.panel_stats),
  };
}

function parseBuildTalents(build: PlayerElfBuildOut): DamageCalculatorTalentInput {
  return { ...emptyTalents, ...safeParseRecord(build.individual_talent_distribution_json) };
}

function parseBuildPanel(build: PlayerElfBuildOut): DamageCalculatorPanelInput | null {
  const raw = safeParseRecord(build.final_stats_json);
  const panel: Partial<DamageCalculatorPanelInput> = {};
  for (const key of statKeys) {
    const value = raw[key];
    if (typeof value !== "number") return null;
    panel[key] = value;
  }
  return panel as DamageCalculatorPanelInput;
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

function fillFromPlayerBuild(build: PlayerElfBuildOut): ParticipantForm {
  const panel = parseBuildPanel(build);
  return {
    elf_id: build.elf_id,
    nature_id: build.nature_id,
    talents: parseBuildTalents(build),
    panel_stats: panel,
    use_panel_stats: false,
  };
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

function combineTypeMultipliers(values: number[]): number {
  if (values.length === 0) return 1;
  if (values.length === 1) return values[0];
  const [first, second] = values;
  const pair = new Set([first, second]);
  if (first === 2 && second === 2) return 3;
  if (first === 0.5 && second === 0.5) return 0.3333333333333333;
  if (pair.has(2) && pair.has(0.5)) return 1;
  if (pair.has(2) && pair.has(1)) return 2;
  if (pair.has(0.5) && pair.has(1)) return 0.5;
  return 1;
}

export function DamageCalculatorPage() {
  const [attacker, setAttacker] = useState<ParticipantForm>(emptyParticipant);
  const [defender, setDefender] = useState<ParticipantForm>(emptyParticipant);
  const [skillId, setSkillId] = useState("");
  const [selectedSkill, setSelectedSkill] = useState<SkillDefinitionOut | null>(null);
  const [modifiers, setModifiers] = useState<ModifierForm>(defaultModifiers);
  const [observedDamage, setObservedDamage] = useState("");
  const [candidateMode, setCandidateMode] = useState<CandidateMode>("focused");
  const [tolerance, setTolerance] = useState("0");
  const [damageSamples, setDamageSamples] = useState<DamageCalculatorInferDefenderSampleInput[]>([]);
  const [mode, setMode] = useState<CalculatorMode>("calculate");
  const [manualModifierFields, setManualModifierFields] = useState<
    Partial<Record<keyof ModifierForm, boolean>>
  >({});
  const [formError, setFormError] = useState<string | null>(null);
  const lastSuggestedModifiers = useRef<Partial<ModifierForm>>({});

  const bootstrap = useQuery({
    queryKey: ["damage-calculator", "bootstrap"],
    queryFn: () => api.damageCalculator.bootstrap(),
  });
  const natures = useQuery({ queryKey: ["natures", "damage-calculator"], queryFn: () => api.natures.list({ limit: 100 }) });
  const attackerDetail = useQuery({
    queryKey: ["elf", attacker.elf_id, "damage-calculator-attacker"],
    queryFn: () => api.elves.get(attacker.elf_id),
    enabled: Boolean(attacker.elf_id),
  });
  const defenderDetail = useQuery({
    queryKey: ["elf", defender.elf_id, "damage-calculator-defender"],
    queryFn: () => api.elves.get(defender.elf_id),
    enabled: Boolean(defender.elf_id),
  });
  const selectedSkillDetail = useQuery({
    queryKey: ["skill", skillId, "damage-calculator-selected"],
    queryFn: () => api.skills.get(skillId),
    enabled: Boolean(skillId) && selectedSkill?.skill_id !== skillId,
  });

  const natureOptions = natures.data ?? [];
  const latestBattle = bootstrap.data?.latest_battle ?? null;
  const latestSkillIds = useMemo(
    () => latestBattle?.self_lineup.find((item) => item.elf_id === attacker.elf_id)?.skill_ids ?? [],
    [attacker.elf_id, latestBattle],
  );
  const effectiveSkill = selectedSkill?.skill_id === skillId ? selectedSkill : selectedSkillDetail.data ?? null;
  const typeRuleMap = useMemo(() => {
    const map = new Map<string, number>();
    for (const rule of bootstrap.data?.type_effectiveness_rules ?? []) {
      const attackType = canonicalElementType(rule.attack_element_type);
      const defenseType = canonicalElementType(rule.defense_element_type);
      if (attackType && defenseType) {
        map.set(`${attackType}:${defenseType}`, rule.multiplier);
      }
    }
    return map;
  }, [bootstrap.data?.type_effectiveness_rules]);
  const calculateMutation = useMutation({
    mutationFn: (payload: DamageCalculatorCalculateInput) => api.damageCalculator.calculate(payload),
  });
  const inferMutation = useMutation({
    mutationFn: (payload: DamageCalculatorInferDefenderInput) => api.damageCalculator.inferDefender(payload),
  });
  const batchInferMutation = useMutation({
    mutationFn: (payload: DamageCalculatorInferDefenderBatchInput) => api.damageCalculator.inferDefenderBatch(payload),
  });

  useEffect(() => {
    if (!effectiveSkill) return;
    const attackerTypes = parseElementTypes(attackerDetail.data?.element_types_json);
    const defenderTypes = parseElementTypes(defenderDetail.data?.element_types_json).slice(0, 2);
    const attackType = canonicalElementType(effectiveSkill.element_type);
    const typeValues = defenderTypes.map((defenseType) => {
      const canonicalDefenseType = canonicalElementType(defenseType);
      return attackType && canonicalDefenseType ? typeRuleMap.get(`${attackType}:${canonicalDefenseType}`) ?? 1 : 1;
    });
    const suggested: Partial<ModifierForm> = {
      stab_multiplier: attackerTypes.some((item) => elementTypeMatches(item, effectiveSkill.element_type)) ? "1.25" : "1",
    };
    if (defenderTypes.length > 0 && typeRuleMap.size > 0) {
      suggested.type_multiplier = String(combineTypeMultipliers(typeValues));
    }
    const hitRule = safeParseRecord(effectiveSkill.hit_rule_json);
    const hitCount = hitRule.hit_count ?? hitRule.combo_count ?? hitRule.fixed_hit_count;
    if (typeof hitCount === "number" && hitCount >= 1) {
      suggested.hit_count = String(hitCount);
    }
    setModifiers((prev) => {
      const next = { ...prev };
      for (const key of Object.keys(suggested) as Array<keyof ModifierForm>) {
        const previousSuggested = lastSuggestedModifiers.current[key];
        if (!manualModifierFields[key] || !next[key] || next[key] === previousSuggested) {
          next[key] = suggested[key] ?? "";
        }
      }
      return next;
    });
    lastSuggestedModifiers.current = suggested;
  }, [
    attackerDetail.data?.element_types_json,
    defenderDetail.data?.element_types_json,
    effectiveSkill,
    manualModifierFields,
    typeRuleMap,
  ]);

  const updateTalent = (role: "attacker" | "defender", key: StatKey, value: number) => {
    const setter = role === "attacker" ? setAttacker : setDefender;
    setter((prev) => ({ ...prev, talents: { ...prev.talents, [key]: value } }));
  };

  const updateModifier = (key: keyof ModifierForm, value: string) => {
    setManualModifierFields((prev) => ({ ...prev, [key]: true }));
    setModifiers((prev) => ({ ...prev, [key]: value }));
  };

  const validate = () => {
    if (!attacker.elf_id) return "请先选择攻击方精灵。";
    if (!defender.elf_id) return "请先选择防御方精灵。";
    if (!skillId) return "请先选择技能。";
    if (!attacker.use_panel_stats && !attacker.nature_id) return "攻击方未使用战斗面板时，需要选择性格。";
    if (!defender.use_panel_stats && !defender.nature_id) return "防御方未使用战斗面板时，需要选择性格。";
    return null;
  };

  const validateInfer = () => {
    if (!attacker.elf_id) return "请先选择攻击方精灵。";
    if (!defender.elf_id) return "请先选择防御方精灵。";
    if (!skillId) return "请先选择技能。";
    if (!attacker.use_panel_stats && !attacker.nature_id) return "攻击方未使用战斗面板时，需要选择性格。";
    if (!observedDamage.trim()) return "请先填写真实伤害，才能反推防御方候选。";
    return null;
  };

  const buildCurrentSample = (): DamageCalculatorInferDefenderSampleInput | null => {
    const error = validateInfer();
    if (error) {
      setFormError(error);
      return null;
    }
    const observed = optionalNumber(observedDamage);
    if (observed === null || observed <= 0) {
      setFormError("真实伤害必须是大于 0 的数字。");
      return null;
    }
    try {
      return {
        attacker: participantPayload(attacker),
        skill_id: skillId,
        formula_type: "attack",
        modifiers: buildModifiers(modifiers, effectiveSkill?.skill_category),
        observed_damage_value: observed,
        label: `${effectiveSkill?.skill_name ?? compactId(skillId)} / 真实 ${observed}`,
      };
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "反推参数解析失败");
      return null;
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const error = validate();
    if (error) {
      setFormError(error);
      return;
    }
    try {
      setFormError(null);
      calculateMutation.mutate({
        attacker: participantPayload(attacker),
        defender: participantPayload(defender),
        skill_id: skillId,
        formula_type: "attack",
        modifiers: buildModifiers(modifiers, effectiveSkill?.skill_category),
        observed_damage_value: null,
      });
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "表单解析失败");
    }
  };

  const inferDefender = () => {
    const error = validateInfer();
    if (error) {
      setFormError(error);
      return;
    }
    try {
      const observed = optionalNumber(observedDamage);
      if (observed === null || observed <= 0) {
        setFormError("真实伤害必须是大于 0 的数字。");
        return;
      }
      setFormError(null);
      inferMutation.mutate({
        attacker: participantPayload(attacker),
        defender_elf_id: defender.elf_id,
        skill_id: skillId,
        formula_type: "attack",
        modifiers: buildModifiers(modifiers, effectiveSkill?.skill_category),
        observed_damage_value: observed,
        top_n: 20,
        candidate_mode: candidateMode,
      });
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "反推参数解析失败");
    }
  };

  const addDamageSample = () => {
    const sample = buildCurrentSample();
    if (!sample) return;
    setDamageSamples((prev) => [...prev, sample]);
    setFormError(null);
  };

  const removeDamageSample = (index: number) => {
    setDamageSamples((prev) => prev.filter((_, itemIndex) => itemIndex !== index));
    batchInferMutation.reset();
  };

  const clearDamageSamples = () => {
    setDamageSamples([]);
    batchInferMutation.reset();
  };

  const inferDefenderBatch = () => {
    if (!defender.elf_id) {
      setFormError("请先选择防御方精灵。");
      return;
    }
    if (damageSamples.length === 0) {
      setFormError("请先至少加入一条真实伤害样本。");
      return;
    }
    const parsedTolerance = optionalNumber(tolerance);
    if (parsedTolerance === null || parsedTolerance < 0) {
      setFormError("容忍偏差必须是大于等于 0 的数字。");
      return;
    }
    setFormError(null);
    batchInferMutation.mutate({
      defender_elf_id: defender.elf_id,
      samples: damageSamples,
      candidate_mode: candidateMode,
      tolerance: Math.floor(parsedTolerance),
      top_n: 20,
    });
  };

  const reset = () => {
    setAttacker(emptyParticipant());
    setDefender(emptyParticipant());
    setSkillId("");
    setSelectedSkill(null);
    setModifiers(defaultModifiers);
    setObservedDamage("");
    setFormError(null);
    calculateMutation.reset();
    inferMutation.reset();
    batchInferMutation.reset();
    setCandidateMode("focused");
    setTolerance("0");
    setDamageSamples([]);
    setMode("calculate");
    lastSuggestedModifiers.current = {};
    setManualModifierFields({});
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">独立伤害计算器</h1>
          <p className="mt-1 text-muted-foreground">
            只读使用静态数据和最近战斗阵容，不创建事件、不修改状态、不写入推算 evidence。
          </p>
        </div>
        <Button variant="outline" onClick={reset} type="button">
          <RotateCcw className="h-4 w-4" />
          重置
        </Button>
      </div>

      {formError ? <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900">{formError}</div> : null}
      {calculateMutation.error ? (
        <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900">
          {calculateMutation.error instanceof Error ? calculateMutation.error.message : "计算失败"}
        </div>
      ) : null}
      {inferMutation.error ? (
        <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900">
          {inferMutation.error instanceof Error ? inferMutation.error.message : "反推失败"}
        </div>
      ) : null}
      {batchInferMutation.error ? (
        <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900">
          {batchInferMutation.error instanceof Error ? batchInferMutation.error.message : "累计反推失败"}
        </div>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>最近战斗快捷导入</CardTitle>
          <CardDescription>
            可把最新一场战斗中的己方/敌方精灵带入表单。导入后默认优先使用当时面板，避免重新配置性格资质。
          </CardDescription>
        </CardHeader>
        <CardContent>
          {latestBattle ? (
            <div className="grid gap-4 lg:grid-cols-2">
              <BattleImportSelect title="己方阵容" items={latestBattle.self_lineup} onPick={(item) => setAttacker(fillFromBattleOption(item))} />
              <BattleImportSelect title="敌方阵容" items={latestBattle.enemy_lineup} onPick={(item) => setDefender(fillFromBattleOption(item))} />
            </div>
          ) : (
            <div className="text-sm text-muted-foreground">
              {bootstrap.isLoading ? "正在读取最近战斗..." : "当前没有可导入的战斗记录，可以直接手动搜索精灵。"}
            </div>
          )}
        </CardContent>
      </Card>

      <form className="grid gap-6 xl:grid-cols-[1fr_420px]" onSubmit={submit}>
        <div className="space-y-6">
          <div className="grid gap-6 lg:grid-cols-2">
            <ParticipantCard
              title="攻击方"
              form={attacker}
              setForm={setAttacker}
              natureOptions={natureOptions}
              onTalentChange={(key, value) => updateTalent("attacker", key, value)}
              onBuildPicked={(build) => {
                if (build.skill_ids.length > 0) {
                  setSkillId(build.skill_ids[0]);
                  setSelectedSkill(null);
                }
              }}
            />
            <ParticipantCard
              title="防御方"
              form={defender}
              setForm={setDefender}
              natureOptions={natureOptions}
              onTalentChange={(key, value) => updateTalent("defender", key, value)}
            />
          </div>

          <Card>
            <CardHeader>
              <CardTitle>技能与修正</CardTitle>
              <CardDescription>手动修正项会覆盖或补充规则解析结果；不确定的机制可以先留空。</CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              <SkillSearchSelect
                label="技能"
                value={skillId}
                elfId={attacker.elf_id || null}
                resultsMode="focus"
                onChange={(id, skill) => {
                  setSkillId(id);
                  setSelectedSkill(skill);
                }}
              />
              {latestSkillIds.length > 0 ? (
                <div className="rounded-xl border bg-slate-50 p-3 text-xs text-slate-600">
                  最近战斗中该攻击方已记录技能：{latestSkillIds.map(compactId).join("、")}
                </div>
              ) : null}
              {effectiveSkill ? (
                <div className="rounded-xl border bg-white p-3 text-sm">
                  <div className="font-medium">{effectiveSkill.skill_name}</div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {effectiveSkill.element_type} / {skillCategoryName(effectiveSkill.skill_category)} / 威力 {effectiveSkill.base_power ?? "—"} / 能耗 {effectiveSkill.base_energy_cost}
                  </div>
                  {effectiveSkill.raw_description ? <div className="mt-2 rounded-lg bg-slate-50 p-2 text-xs text-slate-700">{effectiveSkill.raw_description}</div> : null}
                </div>
              ) : null}

              <div className="rounded-2xl border bg-slate-50 p-4">
                <div className="text-sm font-semibold">状态类修正</div>
                <div className="mt-1 text-xs text-muted-foreground">
                  每层属性增减按 10% 处理，技能威力每层 ±10；物理技能读取物攻/物防，魔法技能读取魔攻/魔防。这里会转换成后端已有公式字段，不写入战斗状态栏。
                </div>
                <div className="mt-3 grid gap-3 md:grid-cols-3">
                  <NumberField label="攻击方物攻增加层数" value={modifiers.attacker_physical_attack_up_layers} onChange={(value) => updateModifier("attacker_physical_attack_up_layers", value)} placeholder="0" />
                  <NumberField label="攻击方物攻降低层数" value={modifiers.attacker_physical_attack_down_layers} onChange={(value) => updateModifier("attacker_physical_attack_down_layers", value)} placeholder="0" />
                  <NumberField label="攻击方魔攻增加层数" value={modifiers.attacker_magic_attack_up_layers} onChange={(value) => updateModifier("attacker_magic_attack_up_layers", value)} placeholder="0" />
                  <NumberField label="攻击方魔攻降低层数" value={modifiers.attacker_magic_attack_down_layers} onChange={(value) => updateModifier("attacker_magic_attack_down_layers", value)} placeholder="0" />
                  <NumberField label="防御方物防增加层数" value={modifiers.defender_physical_defense_up_layers} onChange={(value) => updateModifier("defender_physical_defense_up_layers", value)} placeholder="0" />
                  <NumberField label="防御方物防降低层数" value={modifiers.defender_physical_defense_down_layers} onChange={(value) => updateModifier("defender_physical_defense_down_layers", value)} placeholder="0" />
                  <NumberField label="防御方魔防增加层数" value={modifiers.defender_magic_defense_up_layers} onChange={(value) => updateModifier("defender_magic_defense_up_layers", value)} placeholder="0" />
                  <NumberField label="防御方魔防降低层数" value={modifiers.defender_magic_defense_down_layers} onChange={(value) => updateModifier("defender_magic_defense_down_layers", value)} placeholder="0" />
                  <NumberField label="技能威力增加层数" value={modifiers.skill_power_up_layers} onChange={(value) => updateModifier("skill_power_up_layers", value)} placeholder="例如 4 表示 +40" />
                  <NumberField label="技能威力降低层数" value={modifiers.skill_power_down_layers} onChange={(value) => updateModifier("skill_power_down_layers", value)} placeholder="0" />
                </div>
              </div>
              <div className="grid gap-3 md:grid-cols-3">
                <NumberField label="天气倍率" value={modifiers.weather_multiplier} onChange={(value) => updateModifier("weather_multiplier", value)} placeholder="默认 1" />
                <NumberField label="本系倍率覆盖" value={modifiers.stab_multiplier} onChange={(value) => updateModifier("stab_multiplier", value)} placeholder="按技能/精灵预填" />
                <NumberField label="克制倍率覆盖" value={modifiers.type_multiplier} onChange={(value) => updateModifier("type_multiplier", value)} placeholder="按技能/目标预填" />
                <NumberField label="连击次数" value={modifiers.hit_count} onChange={(value) => updateModifier("hit_count", value)} placeholder="留空按规则" />
                <NumberField label="目标血量" value={modifiers.defender_hp_percent} onChange={(value) => updateModifier("defender_hp_percent", value)} placeholder="可选" />
              </div>
              <details className="rounded-xl border bg-white p-3 text-sm">
                <summary className="cursor-pointer font-medium">高级公式覆盖</summary>
                <div className="mt-3 grid gap-3 md:grid-cols-3">
                  <NumberField label="固定威力修正" value={modifiers.flat_power_bonus} onChange={(value) => updateModifier("flat_power_bonus", value)} placeholder="一般用威力层数" />
                  <NumberField label="威力倍率覆盖" value={modifiers.power_multiplier} onChange={(value) => updateModifier("power_multiplier", value)} placeholder="不确定可留空" />
                  <NumberField label="能力倍率覆盖" value={modifiers.stat_stage_multiplier} onChange={(value) => updateModifier("stat_stage_multiplier", value)} placeholder="不确定可留空" />
                  <NumberField label="额外倍率覆盖" value={modifiers.unstable_multiplier} onChange={(value) => updateModifier("unstable_multiplier", value)} placeholder="不确定可留空" />
                </div>
              </details>
              <div className="grid gap-3 md:grid-cols-2">
                <label className="space-y-1 text-sm">
                  <span className="font-medium">减伤比例</span>
                  <div className="flex overflow-hidden rounded-xl border bg-white focus-within:ring-2 focus-within:ring-ring">
                    <Input className="border-0 focus:ring-0" value={modifiers.damage_reductions} onChange={(event) => updateModifier("damage_reductions", event.target.value)} placeholder="例如 90, 75" />
                    <span className="flex items-center px-3 text-sm text-muted-foreground">%</span>
                  </div>
                  <span className="text-xs text-muted-foreground">多个减伤用逗号或空格分隔；填 90 表示减伤 90%。</span>
                </label>
                <label className="space-y-1 text-sm">
                  <span className="font-medium">条件标记 JSON</span>
                  <Input value={modifiers.condition_flags_json} onChange={(event) => updateModifier("condition_flags_json", event.target.value)} placeholder='例如 {"self_switched_this_turn": true}' />
                </label>
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="space-y-6">
          <Card className="sticky top-6">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Calculator className="h-5 w-5" />
                计算结果
              </CardTitle>
              <CardDescription>理论伤害来自当前后端公式链，未知因素会在结果中展示。</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-2 rounded-2xl bg-slate-100 p-1">
                <button
                  type="button"
                  className={`rounded-xl px-3 py-2 text-sm font-medium transition-all duration-200 ${mode === "calculate" ? "bg-white text-primary shadow-sm" : "text-muted-foreground hover:bg-white/70"}`}
                  onClick={() => setMode("calculate")}
                >
                  单纯计算伤害
                </button>
                <button
                  type="button"
                  className={`rounded-xl px-3 py-2 text-sm font-medium transition-all duration-200 ${mode === "infer" ? "bg-white text-primary shadow-sm" : "text-muted-foreground hover:bg-white/70"}`}
                  onClick={() => setMode("infer")}
                >
                  反推防御方
                </button>
              </div>

              <div className="transition-all duration-300 ease-out">
                {mode === "calculate" ? (
                  <div className="space-y-4 animate-in fade-in slide-in-from-bottom-2 duration-300">
                    <Button className="w-full" type="submit" disabled={calculateMutation.isPending}>
                      {calculateMutation.isPending ? "计算中..." : "计算伤害"}
                    </Button>
                    {calculateMutation.data ? <ResultPanel result={calculateMutation.data} /> : <div className="rounded-xl border border-dashed p-4 text-sm text-muted-foreground">填写精灵、技能和修正项后点击计算。</div>}
                  </div>
                ) : (
                  <div className="space-y-4 animate-in fade-in slide-in-from-bottom-2 duration-300">
                    <label className="block space-y-1 text-sm">
                      <span className="font-medium">真实伤害</span>
                      <Input value={observedDamage} onChange={(event) => setObservedDamage(event.target.value)} placeholder="填写实战看到的伤害，用于反推候选" />
                    </label>
                    <Button
                      className="w-full"
                      variant="outline"
                      type="button"
                      disabled={inferMutation.isPending}
                      onClick={inferDefender}
                    >
                      {inferMutation.isPending ? "反推中..." : "根据真实伤害反推防御方"}
                    </Button>
                    <div className="space-y-3 rounded-xl border bg-slate-50 p-3">
                      <div className="grid gap-3 sm:grid-cols-2">
                        <label className="space-y-1 text-sm">
                          <span className="font-medium">候选模式</span>
                          <Select
                            value={candidateMode}
                            onChange={(event) => setCandidateMode(event.target.value as CandidateMode)}
                          >
                            <option value="focused">聚焦防御线</option>
                            <option value="default_templates">默认资质模板</option>
                          </Select>
                        </label>
                        <NumberField
                          label="容忍偏差"
                          value={tolerance}
                          onChange={setTolerance}
                          placeholder="例如 0 或 2"
                        />
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <Button type="button" variant="outline" size="sm" onClick={addDamageSample}>
                          加入累计样本
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          disabled={batchInferMutation.isPending || damageSamples.length === 0}
                          onClick={inferDefenderBatch}
                        >
                          {batchInferMutation.isPending ? "累计反推中..." : "累计反推"}
                        </Button>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          disabled={damageSamples.length === 0}
                          onClick={clearDamageSamples}
                        >
                          清空累计/新开计算
                        </Button>
                      </div>
                      <DamageSampleList samples={damageSamples} onRemove={removeDamageSample} />
                    </div>
                    {inferMutation.data ? <InferencePanel result={inferMutation.data} /> : null}
                    {batchInferMutation.data ? <BatchInferencePanel result={batchInferMutation.data} /> : null}
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        </div>
      </form>
    </div>
  );
}

function BattleImportSelect({
  title,
  items,
  onPick,
}: {
  title: string;
  items: DamageCalculatorBattleOptionOut[];
  onPick: (item: DamageCalculatorBattleOptionOut) => void;
}) {
  const [selectedKey, setSelectedKey] = useState("");
  const selected = items.find((item) => `${item.side}:${item.elf_id}` === selectedKey);
  return (
    <div className="space-y-2">
      <div className="text-sm font-medium">{title}</div>
      {items.length === 0 ? <div className="rounded-xl border border-dashed p-3 text-sm text-muted-foreground">暂无记录</div> : (
        <div className="flex gap-2">
          <Select
            value={selectedKey}
            onChange={(event) => {
              const key = event.target.value;
              setSelectedKey(key);
              const item = items.find((row) => `${row.side}:${row.elf_id}` === key);
              if (item) onPick(item);
            }}
          >
            <option value="">请选择要导入的精灵</option>
            {items.map((item) => (
              <option key={`${item.side}:${item.elf_id}`} value={`${item.side}:${item.elf_id}`}>
                {item.is_active_elf ? "【场上】" : ""}{item.elf_name} · {panelText(item.panel_stats)}
              </option>
            ))}
          </Select>
        </div>
      )}
      {selected ? (
        <div className="flex items-center gap-3 rounded-xl border bg-slate-50 p-3 text-sm">
          <AvatarImage src={selected.avatar ?? undefined} alt={selected.elf_name} fallback={selected.elf_name} className="h-10 w-10" />
          <div className="min-w-0">
            <div className="truncate font-medium">{selected.elf_name}</div>
            <div className="truncate text-xs text-muted-foreground">{panelText(selected.panel_stats)}</div>
          </div>
          {selected.is_active_elf ? <Badge className="ml-auto">场上</Badge> : null}
        </div>
      ) : null}
    </div>
  );
}

function ParticipantCard({
  title,
  form,
  setForm,
  natureOptions,
  onTalentChange,
  onBuildPicked,
}: {
  title: string;
  form: ParticipantForm;
  setForm: Dispatch<SetStateAction<ParticipantForm>>;
  natureOptions: Array<{ nature_id: string; nature_name: string; positive_stat: string; negative_stat: string }>;
  onTalentChange: (key: StatKey, value: number) => void;
  onBuildPicked?: (build: PlayerElfBuildOut) => void;
}) {
  const selectedElf = useQuery({
    queryKey: ["elf", form.elf_id, "damage-calculator"],
    queryFn: () => api.elves.get(form.elf_id),
    enabled: Boolean(form.elf_id),
  });
  const playerBuilds = useQuery({
    queryKey: ["player-builds", form.elf_id || "all", "damage-calculator"],
    queryFn: () => api.playerBuilds.list(form.elf_id || undefined),
  });
  const elements = parseElementTypes(selectedElf.data?.element_types_json);
  const applyNaturePreset = (natureId: string) => {
    const nature = natureOptions.find((item) => item.nature_id === natureId);
    setForm((prev) => ({
      ...prev,
      nature_id: natureId,
      talents: nature ? defaultTalentsForNature(nature, selectedElf.data) : prev.talents,
    }));
  };
  const applyBuild = (buildId: string) => {
    const build = (playerBuilds.data ?? []).find((item) => item.build_id === buildId);
    if (build) {
      setForm(fillFromPlayerBuild(build));
      onBuildPicked?.(build);
    }
  };
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-3">
          <AvatarImage
            src={selectedElf.data?.avatar}
            alt={selectedElf.data?.elf_name ?? title}
            fallback={selectedElf.data?.elf_name ?? title}
            className="h-12 w-12"
          />
          <div>
            <CardTitle>{title}</CardTitle>
            <CardDescription>{form.elf_id ? `${selectedElf.data?.elf_name ?? compactId(form.elf_id)} ${elements.length > 0 ? ` / ${elementTypeNames(elements)}` : ""}` : "请选择精灵"}</CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <ElfSearchSelect
          label={`${title}精灵`}
          value={form.elf_id}
          resultsMode="focus"
          onChange={(id) => setForm((prev) => ({ ...prev, elf_id: id, panel_stats: null, use_panel_stats: false }))}
        />
        <label className="block space-y-1 text-sm">
          <span className="font-medium">导入已保存配置</span>
          <Select value="" onChange={(event) => applyBuild(event.target.value)} disabled={(playerBuilds.data?.length ?? 0) === 0}>
            <option value="">{(playerBuilds.data?.length ?? 0) > 0 ? "选择一个己方配置导入" : "暂无可导入配置"}</option>
            {(playerBuilds.data ?? []).map((build) => (
              <option key={build.build_id} value={build.build_id}>
                {build.build_name ?? build.elf_name ?? compactId(build.build_id)}{build.is_default ? " · 默认" : ""}
              </option>
            ))}
          </Select>
        </label>
        {form.panel_stats ? (
          <label className="flex items-start gap-2 rounded-xl border bg-slate-50 p-3 text-sm">
            <input
              className="mt-1"
              type="checkbox"
              checked={form.use_panel_stats}
              onChange={(event) => setForm((prev) => ({ ...prev, use_panel_stats: event.target.checked }))}
            />
            <span>
              <span className="block font-medium">使用导入面板</span>
              <span className="mt-1 block text-xs text-muted-foreground">{panelText(form.panel_stats)}</span>
            </span>
          </label>
        ) : null}
        <label className="block space-y-1 text-sm">
          <span className="font-medium">性格</span>
          <Select value={form.nature_id} onChange={(event) => applyNaturePreset(event.target.value)} disabled={form.use_panel_stats}>
            <option value="">请选择性格</option>
            {natureOptions.map((nature) => (
              <option key={nature.nature_id} value={nature.nature_id}>
                {nature.nature_name}（+{statName(nature.positive_stat)} / -{statName(nature.negative_stat)}）
              </option>
            ))}
          </Select>
        </label>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={form.use_panel_stats || !form.nature_id}
          onClick={() => applyNaturePreset(form.nature_id)}
        >
          按当前性格重置资质
        </Button>
        <div className="grid grid-cols-2 gap-3">
          {statKeys.map((key) => (
            <TalentSelect
              key={key}
              label={statName(key)}
              value={Number(form.talents[key] ?? 0)}
              disabled={form.use_panel_stats}
              onChange={(value) => onTalentChange(key, Math.max(0, Math.min(10, Number(value) || 0)))}
            />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function NumberField({
  label,
  value,
  onChange,
  placeholder,
  disabled = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
}) {
  return (
    <label className="block space-y-1 text-sm">
      <span className="font-medium">{label}</span>
      <Input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} disabled={disabled} />
    </label>
  );
}

function TalentSelect({
  label,
  value,
  onChange,
  disabled = false,
}: {
  label: string;
  value: number;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  return (
    <label className="block space-y-1 text-sm">
      <span className="font-medium">{label}</span>
      <Select value={String(value)} onChange={(event) => onChange(event.target.value)} disabled={disabled}>
        <option value="0">不点</option>
        {[7, 8, 9, 10].map((item) => (
          <option key={item} value={item}>{item}</option>
        ))}
      </Select>
    </label>
  );
}

function DamageSampleList({
  samples,
  onRemove,
}: {
  samples: DamageCalculatorInferDefenderSampleInput[];
  onRemove: (index: number) => void;
}) {
  if (samples.length === 0) {
    return (
      <div className="rounded-lg border border-dashed bg-white p-3 text-xs text-muted-foreground">
        暂无累计样本。可以先填本次真实伤害，再加入累计样本；清空后即为新开一次计算。
      </div>
    );
  }
  return (
    <div className="space-y-2">
      <div className="text-xs font-medium text-muted-foreground">已累计 {samples.length} 条样本</div>
      {samples.map((sample, index) => (
        <div
          key={`${sample.skill_id}:${sample.observed_damage_value}:${index}`}
          className="flex items-center justify-between gap-3 rounded-lg border bg-white px-3 py-2 text-xs"
        >
          <span className="min-w-0 truncate">
            #{index + 1} {sample.label ?? compactId(sample.skill_id)}，真实 {sample.observed_damage_value}
          </span>
          <Button type="button" variant="ghost" size="sm" onClick={() => onRemove(index)}>
            移除
          </Button>
        </div>
      ))}
    </div>
  );
}

function ResultPanel({ result }: { result: Awaited<ReturnType<typeof api.damageCalculator.calculate>> }) {
  return (
    <div className="space-y-4">
      <div className="rounded-2xl border bg-primary/5 p-4">
        <div className="text-sm text-muted-foreground">预计伤害</div>
        <div className="mt-1 text-3xl font-bold">{result.damage_value ?? "无法计算"}</div>
        <div className="mt-1 text-sm text-muted-foreground">
          {result.damage_percent !== null && result.damage_percent !== undefined ? `约 ${result.damage_percent}% 最大生命` : "缺少目标生命或公式上下文"}
        </div>
      </div>
      <div className="grid gap-2 text-sm">
        <InfoRow label="状态" value={result.status} />
        <InfoRow label="技能" value={result.skill_name ?? result.skill_id} />
        <InfoRow label="置信度" value={String(result.confidence)} />
        <InfoRow label="攻击方面板" value={panelText(result.attacker.panel_stats)} />
        <InfoRow label="防御方面板" value={panelText(result.defender.panel_stats)} />
      </div>
      {result.observed_comparison ? (
        <div className="rounded-xl border bg-white p-3 text-sm">
          <div className="font-medium">真实伤害对比</div>
          <div className="mt-1 text-muted-foreground">
            真实 {result.observed_comparison.observed_damage_value}，偏差 {result.observed_comparison.delta_value ?? "—"}
            {result.observed_comparison.delta_percent_of_prediction !== null && result.observed_comparison.delta_percent_of_prediction !== undefined ? `（${result.observed_comparison.delta_percent_of_prediction}%）` : ""}
          </div>
          <div className="mt-1 text-xs text-muted-foreground">{result.observed_comparison.message}</div>
        </div>
      ) : null}
      {result.unknown_factors.length > 0 ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          未知因素：{result.unknown_factors.join("、")}
        </div>
      ) : null}
      {result.missing_parts.length > 0 ? (
        <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-900">
          缺失上下文：{result.missing_parts.join("、")}
        </div>
      ) : null}
      <details className="rounded-xl border bg-white p-3 text-sm">
        <summary className="cursor-pointer font-medium">倍率与解释链</summary>
        <pre className="mt-3 max-h-72 overflow-auto rounded-lg bg-slate-950 p-3 text-xs text-slate-50">
          {JSON.stringify({ multipliers: result.multipliers, explanation: result.explanation }, null, 2)}
        </pre>
      </details>
    </div>
  );
}

function InferencePanel({ result }: { result: DamageCalculatorInferDefenderOut }) {
  return (
    <div className="space-y-3 rounded-2xl border bg-white p-4">
      <div>
        <div className="font-semibold">防御方配置候选</div>
        <div className="mt-1 text-xs text-muted-foreground">
          已枚举 {result.searched_candidate_count} 个软候选，显示前 {result.returned_candidate_count} 个；不会写入战斗推算。
        </div>
      </div>
      <div className="space-y-2">
        {result.candidates.map((candidate) => (
          <div key={`${candidate.rank}:${candidate.nature_id}:${candidate.hp_talent}:${candidate.defense_talent}`} className="rounded-xl border bg-slate-50 p-3 text-sm">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="font-medium">
                  #{candidate.rank} {candidate.nature_name}
                  {candidate.template_name ? (
                    <span className="ml-2 text-xs text-muted-foreground">{candidate.template_name}</span>
                  ) : null}
                </div>
                <div className="mt-1 text-xs text-muted-foreground">
                  HP资质 {candidate.hp_talent} / {statName(candidate.relevant_defense_stat)}资质 {candidate.defense_talent}
                </div>
              </div>
              <Badge variant={candidate.absolute_delta === 0 ? "success" : "outline"}>
                偏差 {candidate.delta_value ?? "—"}
              </Badge>
            </div>
            <div className="mt-2 grid gap-1 text-xs text-muted-foreground">
              <div>预测伤害：{candidate.predicted_damage_value ?? "无法计算"}{candidate.predicted_damage_percent !== null && candidate.predicted_damage_percent !== undefined ? `（${candidate.predicted_damage_percent}%）` : ""}</div>
              <div>候选面板：{panelText(candidate.panel_stats)}</div>
              <div>
                候选资质：HP {candidate.individual_talent_distribution.hp ?? 0} / 物攻 {candidate.individual_talent_distribution.physical_attack ?? 0} / 物防 {candidate.individual_talent_distribution.physical_defense ?? 0} / 魔攻 {candidate.individual_talent_distribution.magic_attack ?? 0} / 魔防 {candidate.individual_talent_distribution.magic_defense ?? 0} / 速度 {candidate.individual_talent_distribution.speed ?? 0}
              </div>
              <div>匹配分：{candidate.score}</div>
            </div>
            {candidate.unknown_factors.length > 0 ? (
              <div className="mt-2 rounded-lg bg-amber-50 px-2 py-1 text-xs text-amber-900">
                未知因素：{candidate.unknown_factors.join("、")}
              </div>
            ) : null}
          </div>
        ))}
      </div>
      <details className="rounded-xl border bg-slate-50 p-3 text-xs text-muted-foreground">
        <summary className="cursor-pointer font-medium text-foreground">反推假设</summary>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          {result.assumptions.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </details>
    </div>
  );
}

function BatchInferencePanel({ result }: { result: DamageCalculatorInferDefenderBatchOut }) {
  return (
    <div className="space-y-3 rounded-2xl border bg-white p-4">
      <div>
        <div className="font-semibold">累计伤害反推</div>
        <div className="mt-1 text-xs text-muted-foreground">
          已枚举 {result.searched_candidate_count} 个软候选，显示前 {result.returned_candidate_count} 个；容忍偏差 {result.tolerance}。
          本结果只在独立计算器内展示，不写入战斗推算。
        </div>
      </div>
      <div className="space-y-2">
        {result.candidates.map((candidate) => (
          <div
            key={`${candidate.rank}:${candidate.nature_id}:${candidate.template_name ?? "focused"}:${candidate.hp_talent}:${candidate.physical_defense_talent}:${candidate.magic_defense_talent}`}
            className="rounded-xl border bg-slate-50 p-3 text-sm"
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="font-medium">
                  #{candidate.rank} {candidate.nature_name}
                  {candidate.template_name ? (
                    <span className="ml-2 text-xs text-muted-foreground">{candidate.template_name}</span>
                  ) : null}
                </div>
                <div className="mt-1 text-xs text-muted-foreground">
                  HP {candidate.hp_talent} / 物防 {candidate.physical_defense_talent} / 魔防 {candidate.magic_defense_talent}
                </div>
              </div>
              <Badge variant={candidate.total_absolute_delta === 0 ? "success" : "outline"}>
                总偏差 {candidate.total_absolute_delta}
              </Badge>
            </div>
            <div className="mt-2 grid gap-1 text-xs text-muted-foreground">
              <div>
                命中 {candidate.matched_sample_count}/{candidate.sample_count}，平均偏差 {candidate.average_absolute_delta}，匹配分 {candidate.score}
              </div>
              <div>候选面板：{panelText(candidate.panel_stats)}</div>
              <div>
                相关防御线：{candidate.relevant_defense_stats.map((item) => statName(item)).join("、")}
              </div>
            </div>
            <details className="mt-2 rounded-lg border bg-white p-2 text-xs">
              <summary className="cursor-pointer font-medium">逐条样本偏差</summary>
              <div className="mt-2 space-y-1 text-muted-foreground">
                {candidate.sample_results.map((sample) => (
                  <div key={`${sample.sample_index}:${sample.skill_id}`} className="rounded bg-slate-50 px-2 py-1">
                    #{sample.sample_index + 1} {sample.sample_label ?? sample.skill_name ?? compactId(sample.skill_id)}：
                    真实 {sample.observed_damage_value} / 预测 {sample.predicted_damage_value ?? "无法计算"} / 偏差 {sample.delta_value ?? "—"}
                    {sample.matched_within_tolerance ? " / 命中容忍" : ""}
                  </div>
                ))}
              </div>
            </details>
          </div>
        ))}
      </div>
      <details className="rounded-xl border bg-slate-50 p-3 text-xs text-muted-foreground">
        <summary className="cursor-pointer font-medium text-foreground">累计反推假设</summary>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          {result.assumptions.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </details>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3 rounded-xl border bg-white px-3 py-2">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right font-medium">{value}</span>
    </div>
  );
}
