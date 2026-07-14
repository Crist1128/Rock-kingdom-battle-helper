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
  DamageCalculatorInferAttackerInput,
  DamageCalculatorInferAttackerOut,
  DamageCalculatorInferDefenderInput,
  DamageCalculatorInferDefenderOut,
  DamageCalculatorModifierInput,
  DamageCalculatorPanelInput,
  DamageCalculatorTalentInput,
  ElfDefinitionOut,
  NatureDefinitionOut,
  SkillDefinitionOut,
} from "@/types/api";
import { canonicalElementType, compactId, elementTypeMatches, elementTypeNames, parseElementTypes, skillCategoryName, statName } from "@/lib/utils";

const statKeys = ["hp", "physical_attack", "physical_defense", "magic_attack", "magic_defense", "speed"] as const;

type StatKey = (typeof statKeys)[number];
type CalculatorMode = "calculate" | "infer_defender" | "infer_attacker";

interface ParticipantForm {
  elf_id: string;
  nature_id: string;
  talents: DamageCalculatorTalentInput;
  panel_stats: DamageCalculatorPanelInput | null;
  use_panel_stats: boolean;
  imported_nature_id: string;
  imported_talents: DamageCalculatorTalentInput | null;
}

interface ModifierForm {
  weather_multiplier: string;
  base_power_override: string;
  power_multiplier: string;
  flat_power_bonus: string;
  stat_stage_multiplier: string;
  stab_multiplier: string;
  type_multiplier: string;
  unstable_multiplier: string;
  damage_reductions: string;
  hit_count: string;
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
  imported_nature_id: "",
  imported_talents: null,
});

const defaultModifiers: ModifierForm = {
  weather_multiplier: "",
  base_power_override: "",
  power_multiplier: "",
  flat_power_bonus: "",
  stat_stage_multiplier: "",
  stab_multiplier: "",
  type_multiplier: "",
  unstable_multiplier: "",
  damage_reductions: "",
  hit_count: "",
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

function hasAnyPositiveTalent(talents: DamageCalculatorTalentInput): boolean {
  return statKeys.some((key) => Number(talents[key] ?? 0) > 0);
}

function formatValidationErrors(errors: string[]): string | null {
  if (errors.length === 0) return null;
  if (errors.length === 1) return errors[0];
  return `请先补齐以下信息：\n${errors.map((item) => `- ${item}`).join("\n")}`;
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

function buildModifiers(
  form: ModifierForm,
  skillCategory?: string | null,
): DamageCalculatorModifierInput {
  const hitCount = optionalNumber(form.hit_count);
  const manualStatStage = optionalNumber(form.stat_stage_multiplier);
  const statStageMultiplier = manualStatStage ?? computedStatStageMultiplier(form, skillCategory);
  return {
    weather_multiplier: optionalNumber(form.weather_multiplier),
    base_power_override: optionalNumber(form.base_power_override),
    power_multiplier: optionalNumber(form.power_multiplier),
    flat_power_bonus: computedFlatPowerBonus(form),
    stat_stage_multiplier: statStageMultiplier,
    stab_multiplier: optionalNumber(form.stab_multiplier),
    type_multiplier: optionalNumber(form.type_multiplier),
    unstable_multiplier: optionalNumber(form.unstable_multiplier),
    damage_reductions: parseReductionList(form.damage_reductions),
    hit_count: hitCount === null ? null : Math.max(1, Math.floor(hitCount)),
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
  const importedNatureId = option.nature_id ?? "";
  const importedTalents = { ...emptyTalents, ...(option.individual_talent_distribution ?? {}) };
  return {
    elf_id: option.elf_id,
    nature_id: importedNatureId,
    talents: { ...importedTalents },
    panel_stats: option.panel_stats ?? null,
    use_panel_stats: Boolean(option.panel_stats),
    imported_nature_id: importedNatureId,
    imported_talents: { ...importedTalents },
  };
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
  if (first === 0.5 && second === 0.5) return 0.25;
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
  const [observedHpBefore, setObservedHpBefore] = useState("");
  const [observedHpAfter, setObservedHpAfter] = useState("");
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
    () => {
      const lineup = mode === "infer_attacker"
        ? latestBattle?.enemy_lineup
        : latestBattle?.self_lineup;
      return lineup?.find((item) => item.elf_id === attacker.elf_id)?.skill_ids ?? [];
    },
    [attacker.elf_id, latestBattle, mode],
  );
  const effectiveSkill = selectedSkill?.skill_id === skillId ? selectedSkill : selectedSkillDetail.data ?? null;
  const isMagicSkill = effectiveSkill?.skill_category === "magic";
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
  const inferAttackerMutation = useMutation({
    mutationFn: (payload: DamageCalculatorInferAttackerInput) => api.damageCalculator.inferAttacker(payload),
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

  const resolvedObservedHpDelta = () => {
    const before = optionalNumber(observedHpBefore);
    const after = optionalNumber(observedHpAfter);
    if (before !== null && after !== null) return before - after;
    return null;
  };

  const participantValidationErrors = (
    participant: ParticipantForm,
    label: string,
    options: { requireNatureAndTalents: boolean },
  ) => {
    const errors: string[] = [];
    if (!participant.elf_id) {
      errors.push(`${label}：请选择精灵`);
      return errors;
    }
    if (participant.use_panel_stats && !participant.panel_stats) {
      errors.push(`${label}：导入面板缺失，请重新从最近战斗导入或取消使用导入面板`);
    }
    if (!participant.use_panel_stats && options.requireNatureAndTalents) {
      if (!participant.nature_id) {
        errors.push(`${label}：请选择性格`);
      }
      if (!hasAnyPositiveTalent(participant.talents)) {
        errors.push(`${label}：请填写/确认资质，当前六维都是“不点/0”`);
      }
    }
    return errors;
  };

  const validate = () => {
    const errors = [
      ...participantValidationErrors(attacker, "攻击方", { requireNatureAndTalents: true }),
      ...participantValidationErrors(defender, "防御方", { requireNatureAndTalents: true }),
    ];
    if (!skillId) errors.push("请选择技能");
    return formatValidationErrors(errors);
  };

  const validateInfer = () => {
    const errors = [
      ...participantValidationErrors(attacker, "攻击方", { requireNatureAndTalents: true }),
    ];
    if (!defender.elf_id) errors.push("防御方：请选择精灵");
    if (!skillId) errors.push("请选择技能");
    const hpDelta = resolvedObservedHpDelta();
    const hpBefore = optionalNumber(observedHpBefore);
    const hpAfter = optionalNumber(observedHpAfter);
    if (hpBefore === null) {
      errors.push("请填写敌方受击前血量百分比");
    }
    if (hpAfter === null) {
      errors.push("请填写敌方受击后血量百分比");
    }
    if (hpBefore !== null && hpAfter !== null && hpDelta !== null && hpDelta <= 0) {
      errors.push("敌方受击前血量必须大于受击后血量");
    }
    const observed = optionalNumber(observedDamage);
    if (observed === null || observed <= 0) {
      errors.push("请填写大于 0 的真实伤害");
    }
    return formatValidationErrors(errors);
  };

  const validateInferAttacker = () => {
    const errors = [
      ...participantValidationErrors(defender, "己方防御方", { requireNatureAndTalents: true }),
    ];
    if (!attacker.elf_id) errors.push("敌方攻击方：请选择精灵");
    if (!skillId) errors.push("请选择敌方使用的技能");
    const observed = optionalNumber(observedDamage);
    if (observed === null || observed <= 0) {
      errors.push("请填写大于 0 的真实伤害");
    }
    return formatValidationErrors(errors);
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (mode === "infer_defender") {
      inferDefender();
      return;
    }
    if (mode === "infer_attacker") {
      inferAttacker();
      return;
    }
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
      const hpBefore = optionalNumber(observedHpBefore);
      const hpAfter = optionalNumber(observedHpAfter);
      const hpDelta = resolvedObservedHpDelta();
      if (observed === null || observed <= 0) {
        setFormError("请填写真实伤害。");
        return;
      }
      if (hpDelta === null || hpDelta <= 0) {
        setFormError("受击前血量必须大于受击后血量。");
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
        observed_hp_percent_before: hpBefore,
        observed_hp_percent_after: hpAfter,
        top_n: 100,
      });
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "反推参数解析失败");
    }
  };

  const inferAttacker = () => {
    const error = validateInferAttacker();
    if (error) {
      setFormError(error);
      return;
    }
    try {
      const observed = optionalNumber(observedDamage);
      if (observed === null || observed <= 0) {
        setFormError("请填写真实伤害。");
        return;
      }
      setFormError(null);
      inferAttackerMutation.mutate({
        attacker_elf_id: attacker.elf_id,
        defender: participantPayload(defender),
        skill_id: skillId,
        formula_type: "attack",
        modifiers: buildModifiers(modifiers, effectiveSkill?.skill_category),
        observed_damage_value: observed,
        top_n: 100,
      });
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "反推参数解析失败");
    }
  };

  const reset = () => {
    setAttacker(emptyParticipant());
    setDefender(emptyParticipant());
    setSkillId("");
    setSelectedSkill(null);
    setModifiers(defaultModifiers);
    setObservedDamage("");
    setObservedHpBefore("");
    setObservedHpAfter("");
    setFormError(null);
    calculateMutation.reset();
    inferMutation.reset();
    inferAttackerMutation.reset();
    setMode("calculate");
    lastSuggestedModifiers.current = {};
    setManualModifierFields({});
  };

  const attackerTitle = mode === "infer_attacker" ? "敌方攻击方" : "攻击方";
  const defenderTitle = mode === "infer_attacker" ? "己方防御方" : "防御方";
  const selfImportTitle = mode === "infer_attacker" ? "己方防御方配置" : "己方攻击方配置";
  const enemyImportTitle = mode === "infer_attacker" ? "敌方攻击方配置" : "敌方防御方配置";

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

      <Card>
        <CardContent className="p-2">
          <div className="grid gap-2 rounded-2xl bg-slate-100 p-1 md:grid-cols-3">
            <ModeTabButton
              active={mode === "calculate"}
              title="单纯计算伤害"
              description="双方配置已知时正向计算"
              onClick={() => {
                setMode("calculate");
                setFormError(null);
              }}
            />
            <ModeTabButton
              active={mode === "infer_defender"}
              title="反推防御方"
              description="已知攻击方、伤害和血量变化"
              onClick={() => {
                setMode("infer_defender");
                setFormError(null);
              }}
            />
            <ModeTabButton
              active={mode === "infer_attacker"}
              title="反推攻击方"
              description="已知己方防御配置和受击伤害"
              onClick={() => {
                setMode("infer_attacker");
                setFormError(null);
              }}
            />
          </div>
        </CardContent>
      </Card>

      {formError ? <ValidationAlert message={formError} /> : null}
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
      {inferAttackerMutation.error ? (
        <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900">
          {inferAttackerMutation.error instanceof Error ? inferAttackerMutation.error.message : "反推攻击方失败"}
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
              <BattleImportSelect
                title={selfImportTitle}
                items={latestBattle.self_lineup}
                onPick={(item) =>
                  mode === "infer_attacker"
                    ? setDefender(fillFromBattleOption(item))
                    : setAttacker(fillFromBattleOption(item))
                }
              />
              <BattleImportSelect
                title={enemyImportTitle}
                items={latestBattle.enemy_lineup}
                onPick={(item) =>
                  mode === "infer_attacker"
                    ? setAttacker(fillFromBattleOption(item))
                    : setDefender(fillFromBattleOption(item))
                }
              />
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
              title={attackerTitle}
              form={attacker}
              setForm={setAttacker}
              natureOptions={natureOptions}
              onTalentChange={(key, value) => updateTalent("attacker", key, value)}
            />
            <ParticipantCard
              title={defenderTitle}
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
                  会按当前技能类别只展示相关攻防修正；物理技能读取物攻/物防，魔法技能读取魔攻/魔防。技能威力层数、自填技能威力和连击数也放在这里统一处理。
                </div>
                <div className="mt-3 grid gap-3 md:grid-cols-3">
                  {isMagicSkill ? (
                    <>
                      <NumberField label="攻击方魔攻增加层数" value={modifiers.attacker_magic_attack_up_layers} onChange={(value) => updateModifier("attacker_magic_attack_up_layers", value)} placeholder="0" />
                      <NumberField label="攻击方魔攻降低层数" value={modifiers.attacker_magic_attack_down_layers} onChange={(value) => updateModifier("attacker_magic_attack_down_layers", value)} placeholder="0" />
                      <NumberField label="防御方魔防增加层数" value={modifiers.defender_magic_defense_up_layers} onChange={(value) => updateModifier("defender_magic_defense_up_layers", value)} placeholder="0" />
                      <NumberField label="防御方魔防降低层数" value={modifiers.defender_magic_defense_down_layers} onChange={(value) => updateModifier("defender_magic_defense_down_layers", value)} placeholder="0" />
                    </>
                  ) : (
                    <>
                      <NumberField label="攻击方物攻增加层数" value={modifiers.attacker_physical_attack_up_layers} onChange={(value) => updateModifier("attacker_physical_attack_up_layers", value)} placeholder="0" />
                      <NumberField label="攻击方物攻降低层数" value={modifiers.attacker_physical_attack_down_layers} onChange={(value) => updateModifier("attacker_physical_attack_down_layers", value)} placeholder="0" />
                      <NumberField label="防御方物防增加层数" value={modifiers.defender_physical_defense_up_layers} onChange={(value) => updateModifier("defender_physical_defense_up_layers", value)} placeholder="0" />
                      <NumberField label="防御方物防降低层数" value={modifiers.defender_physical_defense_down_layers} onChange={(value) => updateModifier("defender_physical_defense_down_layers", value)} placeholder="0" />
                    </>
                  )}
                  <NumberField label="自填技能威力" value={modifiers.base_power_override} onChange={(value) => updateModifier("base_power_override", value)} placeholder="留空用技能原始威力" />
                  <NumberField label="技能威力增加层数" value={modifiers.skill_power_up_layers} onChange={(value) => updateModifier("skill_power_up_layers", value)} placeholder="例如 4 表示 +40" />
                  <NumberField label="技能威力降低层数" value={modifiers.skill_power_down_layers} onChange={(value) => updateModifier("skill_power_down_layers", value)} placeholder="0" />
                  <NumberField label="连击次数" value={modifiers.hit_count} onChange={(value) => updateModifier("hit_count", value)} placeholder="留空按规则" />
                </div>
              </div>
              <div className="grid gap-3 md:grid-cols-3">
                <NumberField label="天气倍率" value={modifiers.weather_multiplier} onChange={(value) => updateModifier("weather_multiplier", value)} placeholder="默认 1" />
                <NumberField label="本系倍率覆盖" value={modifiers.stab_multiplier} onChange={(value) => updateModifier("stab_multiplier", value)} placeholder="按技能/精灵预填" />
                <NumberField label="克制倍率覆盖" value={modifiers.type_multiplier} onChange={(value) => updateModifier("type_multiplier", value)} placeholder="按技能/目标预填" />
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
              <div className="grid gap-3 md:grid-cols-1">
                <label className="space-y-1 text-sm">
                  <span className="font-medium">减伤比例</span>
                  <div className="flex overflow-hidden rounded-xl border bg-white focus-within:ring-2 focus-within:ring-ring">
                    <Input className="border-0 focus:ring-0" value={modifiers.damage_reductions} onChange={(event) => updateModifier("damage_reductions", event.target.value)} placeholder="例如 90, 75" />
                    <span className="flex items-center px-3 text-sm text-muted-foreground">%</span>
                  </div>
                  <span className="text-xs text-muted-foreground">多个减伤用逗号或空格分隔；填 90 表示减伤 90%。</span>
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
              <div key={mode} className="transition-all duration-300 ease-out animate-in fade-in slide-in-from-bottom-2">
                {mode === "calculate" ? (
                  <div className="space-y-4">
                    <Button className="w-full" type="submit" disabled={calculateMutation.isPending}>
                      {calculateMutation.isPending ? "计算中..." : "计算伤害"}
                    </Button>
                    {formError ? <ValidationAlert message={formError} compact /> : null}
                    {calculateMutation.data ? <ResultPanel result={calculateMutation.data} /> : <div className="rounded-xl border border-dashed p-4 text-sm text-muted-foreground">填写精灵、技能和修正项后点击计算。</div>}
                  </div>
                ) : null}
                {mode === "infer_defender" ? (
                  <div className="space-y-4">
                    <div className="rounded-xl border bg-slate-50 p-3 text-xs text-muted-foreground">
                      反推防御方配置必须同时填写真实伤害和受击前后血量百分比；否则无法同时约束 HP 资质和防御资质。
                    </div>
                    <div className="grid gap-3 sm:grid-cols-2">
                      <NumberField label="受击前血量%" value={observedHpBefore} onChange={setObservedHpBefore} placeholder="例如 100" />
                      <NumberField label="受击后血量%" value={observedHpAfter} onChange={setObservedHpAfter} placeholder="例如 72" />
                    </div>
                    <label className="block space-y-1 text-sm">
                      <span className="font-medium">真实伤害</span>
                      <Input value={observedDamage} onChange={(event) => setObservedDamage(event.target.value)} placeholder="例如 157" />
                    </label>
                    <Button
                      className="w-full"
                      variant="outline"
                      type="button"
                      disabled={inferMutation.isPending}
                      onClick={inferDefender}
                    >
                      {inferMutation.isPending ? "反推中..." : "根据伤害和血量反推防御方"}
                    </Button>
                    {formError ? <ValidationAlert message={formError} compact /> : null}
                    {inferMutation.data ? (
                      <InferencePanel result={inferMutation.data} natureOptions={natureOptions} />
                    ) : null}
                  </div>
                ) : null}
                {mode === "infer_attacker" ? (
                  <div className="space-y-4">
                    <div className="rounded-xl border bg-slate-50 p-3 text-xs text-muted-foreground">
                      反推攻击方时，左侧“敌方攻击方”只需要选择精灵；右侧“己方防御方”建议从最近战斗导入己方面板或填写性格资质。
                    </div>
                    <label className="block space-y-1 text-sm">
                      <span className="font-medium">真实伤害</span>
                      <Input value={observedDamage} onChange={(event) => setObservedDamage(event.target.value)} placeholder="例如 157" />
                    </label>
                    <Button
                      className="w-full"
                      variant="outline"
                      type="button"
                      disabled={inferAttackerMutation.isPending}
                      onClick={inferAttacker}
                    >
                      {inferAttackerMutation.isPending ? "反推中..." : "根据伤害反推攻击方"}
                    </Button>
                    {formError ? <ValidationAlert message={formError} compact /> : null}
                    {inferAttackerMutation.data ? (
                      <AttackerInferencePanel result={inferAttackerMutation.data} natureOptions={natureOptions} />
                    ) : null}
                  </div>
                ) : null}
              </div>
            </CardContent>
          </Card>
        </div>
      </form>
    </div>
  );
}

function ValidationAlert({ message, compact = false }: { message: string; compact?: boolean }) {
  const lines = message.split("\n").map((line) => line.trim()).filter(Boolean);
  const title = lines[0] ?? "请检查表单";
  const items = lines.slice(1).map((line) => line.replace(/^- /, ""));
  return (
    <div
      className={`rounded-2xl border border-red-200 bg-red-50 text-sm text-red-900 ${
        compact ? "px-3 py-2" : "px-4 py-3"
      }`}
    >
      <div className="font-medium">{title}</div>
      {items.length > 0 ? (
        <ul className="mt-2 list-disc space-y-1 pl-5">
          {items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function ModeTabButton({
  active,
  title,
  description,
  onClick,
}: {
  active: boolean;
  title: string;
  description: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={`rounded-xl px-4 py-3 text-left transition-all duration-300 ${
        active
          ? "bg-white text-primary shadow-sm ring-1 ring-primary/10"
          : "text-muted-foreground hover:bg-white/70"
      }`}
      onClick={onClick}
    >
      <span className="block text-sm font-semibold">{title}</span>
      <span className="mt-1 block text-xs">{description}</span>
    </button>
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
}: {
  title: string;
  form: ParticipantForm;
  setForm: Dispatch<SetStateAction<ParticipantForm>>;
  natureOptions: Array<{ nature_id: string; nature_name: string; positive_stat: string; negative_stat: string }>;
  onTalentChange: (key: StatKey, value: number) => void;
}) {
  const selectedElf = useQuery({
    queryKey: ["elf", form.elf_id, "damage-calculator"],
    queryFn: () => api.elves.get(form.elf_id),
    enabled: Boolean(form.elf_id),
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
  const toggleImportedPanel = (checked: boolean) => {
    setForm((prev) => {
      if (!checked) {
        return { ...prev, use_panel_stats: false };
      }
      return {
        ...prev,
        use_panel_stats: true,
        nature_id: prev.imported_nature_id || prev.nature_id,
        talents: prev.imported_talents ? { ...emptyTalents, ...prev.imported_talents } : prev.talents,
      };
    });
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
          onChange={(id) =>
            setForm((prev) => ({
              ...prev,
              elf_id: id,
              panel_stats: null,
              use_panel_stats: false,
              imported_nature_id: "",
              imported_talents: null,
            }))
          }
        />
        {form.panel_stats ? (
          <label className="flex items-start gap-2 rounded-xl border bg-slate-50 p-3 text-sm">
            <input
              className="mt-1"
              type="checkbox"
              checked={form.use_panel_stats}
              onChange={(event) => toggleImportedPanel(event.target.checked)}
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

function InferencePanel({
  result,
  natureOptions,
}: {
  result: DamageCalculatorInferDefenderOut;
  natureOptions: NatureDefinitionOut[];
}) {
  const natureById = useMemo(
    () => new Map(natureOptions.map((nature) => [nature.nature_id, nature])),
    [natureOptions],
  );
  const groups = useMemo(() => {
    const grouped = new Map<
      string,
      {
        key: string;
        title: string;
        candidates: typeof result.candidates;
      }
    >();
    for (const candidate of result.candidates) {
      const nature = natureById.get(candidate.nature_id);
      const positiveStat = nature?.positive_stat ?? null;
      const key = positiveStat ?? `unknown:${candidate.nature_name}`;
      const title = positiveStat
        ? `${statName(positiveStat)}+ 性格`
        : `${candidate.nature_name}（正面未知）`;
      const current = grouped.get(key);
      if (current) {
        current.candidates.push(candidate);
      } else {
        grouped.set(key, { key, title, candidates: [candidate] });
      }
    }
    return Array.from(grouped.values()).sort((left, right) => {
      const leftBest = left.candidates[0]?.rank ?? 9999;
      const rightBest = right.candidates[0]?.rank ?? 9999;
      return leftBest - rightBest || left.title.localeCompare(right.title, "zh-CN");
    });
  }, [natureById, result.candidates]);

  return (
    <div className="space-y-3 rounded-2xl border bg-white p-4">
      <div>
        <div className="font-semibold">防御方配置候选</div>
        <div className="mt-1 text-xs text-muted-foreground">
          已枚举 {result.searched_candidate_count} 个候选，返回 {result.returned_candidate_count} 个命中候选；观察扣血 {result.observed_hp_percent_delta ?? "—"}%。
        </div>
        {result.candidates.length > 0 ? (
          <div className="mt-2 rounded-xl border border-blue-100 bg-blue-50 px-3 py-2 text-xs text-blue-900">
            已按正面性格分成 {groups.length} 类，默认全部收起。请点开某一类查看具体性格和三维资质。
          </div>
        ) : null}
      </div>
      <CandidateTalentSummary candidates={result.candidates} />
      {result.candidates.length === 0 ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          没有找到同时满足伤害值和受击前后血量百分比的候选。请检查攻击方面板、技能威力/层数、克制、本系、天气、减伤和连击等修正项。
        </div>
      ) : null}
      <div className="space-y-3">
        {groups.map((group) => {
          const best = group.candidates[0];
          return (
            <details key={group.key} className="overflow-hidden rounded-2xl border bg-slate-50">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-3 border-b bg-white px-4 py-3 transition hover:bg-slate-50 [&::-webkit-details-marker]:hidden">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold text-emerald-700">{group.title}</span>
                    <Badge variant="outline">{group.candidates.length} 个候选</Badge>
                    {best ? <Badge variant="success">最优 #{best.rank}</Badge> : null}
                  </div>
                  {best ? (
                    <div className="mt-1 truncate text-xs text-muted-foreground">
                      最优：{best.nature_name} · {talentSummaryText(best.individual_talent_distribution)}
                    </div>
                  ) : null}
                </div>
                <span className="shrink-0 text-xs text-muted-foreground">点击展开</span>
              </summary>
              <div className="space-y-2 p-3">
                {group.candidates.map((candidate) => (
                  <CandidateCard
                    key={`${candidate.rank}:${candidate.nature_id}:${candidate.hp_talent}:${candidate.defense_talent}:${candidate.template_name ?? ""}`}
                    candidate={candidate}
                  />
                ))}
              </div>
            </details>
          );
        })}
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

function AttackerInferencePanel({
  result,
  natureOptions,
}: {
  result: DamageCalculatorInferAttackerOut;
  natureOptions: NatureDefinitionOut[];
}) {
  const natureById = useMemo(
    () => new Map(natureOptions.map((nature) => [nature.nature_id, nature])),
    [natureOptions],
  );
  const groups = useMemo(() => {
    const grouped = new Map<
      string,
      {
        key: string;
        title: string;
        candidates: typeof result.candidates;
      }
    >();
    for (const candidate of result.candidates) {
      const nature = natureById.get(candidate.nature_id);
      const positiveStat = nature?.positive_stat ?? null;
      const key = positiveStat ?? `unknown:${candidate.nature_name}`;
      const title = positiveStat
        ? `${statName(positiveStat)}+ 性格`
        : `${candidate.nature_name}（正面未知）`;
      const current = grouped.get(key);
      if (current) {
        current.candidates.push(candidate);
      } else {
        grouped.set(key, { key, title, candidates: [candidate] });
      }
    }
    return Array.from(grouped.values()).sort((left, right) => {
      const leftBest = left.candidates[0]?.rank ?? 9999;
      const rightBest = right.candidates[0]?.rank ?? 9999;
      return leftBest - rightBest || left.title.localeCompare(right.title, "zh-CN");
    });
  }, [natureById, result.candidates]);

  return (
    <div className="space-y-3 rounded-2xl border bg-white p-4">
      <div>
        <div className="font-semibold">攻击方配置候选</div>
        <div className="mt-1 text-xs text-muted-foreground">
          已枚举 {result.searched_candidate_count} 个候选，返回 {result.returned_candidate_count} 个命中候选；本技能读取 {statName(result.relevant_attack_stat)}。
        </div>
        {result.candidates.length > 0 ? (
          <div className="mt-2 rounded-xl border border-blue-100 bg-blue-50 px-3 py-2 text-xs text-blue-900">
            候选会标记“是否为 {statName(result.relevant_attack_stat)}+ 性格”和“是否点了 {statName(result.relevant_attack_stat)} 资质”。
          </div>
        ) : null}
      </div>
      <CandidateTalentSummary candidates={result.candidates} />
      {result.candidates.length === 0 ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          没有找到与真实伤害完全一致的攻击方候选。请检查己方防御面板、敌方技能、技能威力、克制、本系、天气、减伤和连击等修正项。
        </div>
      ) : null}
      <div className="space-y-3">
        {groups.map((group) => {
          const best = group.candidates[0];
          return (
            <details key={group.key} className="overflow-hidden rounded-2xl border bg-slate-50">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-3 border-b bg-white px-4 py-3 transition hover:bg-slate-50 [&::-webkit-details-marker]:hidden">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold text-emerald-700">{group.title}</span>
                    <Badge variant="outline">{group.candidates.length} 个候选</Badge>
                    {best ? <Badge variant="success">最优 #{best.rank}</Badge> : null}
                  </div>
                  {best ? (
                    <div className="mt-1 truncate text-xs text-muted-foreground">
                      最优：{best.nature_name} · {talentSummaryText(best.individual_talent_distribution)}
                    </div>
                  ) : null}
                </div>
                <span className="shrink-0 text-xs text-muted-foreground">点击展开</span>
              </summary>
              <div className="space-y-2 p-3">
                {group.candidates.map((candidate) => (
                  <AttackerCandidateCard
                    key={`${candidate.rank}:${candidate.nature_id}:${candidate.attack_talent}:${candidate.template_name ?? ""}`}
                    candidate={candidate}
                  />
                ))}
              </div>
            </details>
          );
        })}
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

function talentSummaryText(talents: DamageCalculatorTalentInput): string {
  const cultivated = statKeys
    .map((key) => ({ key, value: Number(talents[key] ?? 0) }))
    .filter((item) => item.value > 0);
  if (cultivated.length === 0) return "无资质";
  return cultivated.map((item) => `${statName(item.key)} ${item.value}`).join(" / ");
}

type TalentCandidateLike = {
  individual_talent_distribution: DamageCalculatorTalentInput;
};

function buildTalentStats(candidates: TalentCandidateLike[]) {
  const total = candidates.length;
  const counts = statKeys.map((key) => ({
    key,
    count: candidates.filter(
      (candidate) => Number(candidate.individual_talent_distribution[key] ?? 0) > 0,
    ).length,
  }));
  return {
    total,
    allPositive: counts.filter((item) => item.count === total && total > 0),
    counts: counts.sort(
      (left, right) =>
        right.count - left.count || statName(left.key).localeCompare(statName(right.key), "zh-CN"),
    ),
  };
}

function CandidateTalentSummary({ candidates }: { candidates: TalentCandidateLike[] }) {
  if (candidates.length === 0) return null;
  const stats = buildTalentStats(candidates);
  const allPositiveText =
    stats.allPositive.length > 0
      ? stats.allPositive.map((item) => statName(item.key)).join("、")
      : "暂无所有候选共同点的资质";

  return (
    <div className="rounded-2xl border border-emerald-100 bg-emerald-50 p-3 text-xs text-emerald-950">
      <div className="font-semibold">候选资质统计</div>
      <div className="mt-1">所有候选都点了：{allPositiveText}</div>
      <div className="mt-2 flex flex-wrap gap-2">
        {stats.counts.map((item) => (
          <Badge key={item.key} variant={item.count === stats.total ? "success" : "outline"}>
            {statName(item.key)} {item.count}/{stats.total}
          </Badge>
        ))}
      </div>
    </div>
  );
}

function CandidateCard({
  candidate,
}: {
  candidate: DamageCalculatorInferDefenderOut["candidates"][number];
}) {
  return (
    <div className="rounded-xl border bg-white p-3 text-sm shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold">#{candidate.rank} {candidate.nature_name}</span>
            {candidate.template_name ? <Badge variant="outline">{candidate.template_name}</Badge> : null}
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            {statKeys
              .map((key) => ({ key, value: Number(candidate.individual_talent_distribution[key] ?? 0) }))
              .filter((item) => item.value > 0)
              .map((item) => (
                <Badge key={item.key} variant="secondary" className="bg-slate-100 text-slate-700">
                  {statName(item.key)} {item.value}
                </Badge>
              ))}
          </div>
        </div>
        <Badge variant={candidate.matched_within_tolerance ? "success" : "outline"}>命中</Badge>
      </div>
      <div className="mt-2 text-xs text-muted-foreground">
        预测伤害 {candidate.predicted_damage_value ?? "无法计算"}
        {candidate.predicted_damage_percent !== null && candidate.predicted_damage_percent !== undefined
          ? `（${candidate.predicted_damage_percent}%）`
          : ""}
      </div>
      {candidate.unknown_factors.length > 0 ? (
        <div className="mt-2 rounded-lg bg-amber-50 px-2 py-1 text-xs text-amber-900">
          未知因素：{candidate.unknown_factors.join("、")}
        </div>
      ) : null}
    </div>
  );
}

function AttackerCandidateCard({
  candidate,
}: {
  candidate: DamageCalculatorInferAttackerOut["candidates"][number];
}) {
  return (
    <div className="rounded-xl border bg-white p-3 text-sm shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold">#{candidate.rank} {candidate.nature_name}</span>
            {candidate.template_name ? <Badge variant="outline">{candidate.template_name}</Badge> : null}
            {candidate.is_relevant_attack_positive_nature ? (
              <Badge variant="success">{statName(candidate.relevant_attack_stat)}+ 性格</Badge>
            ) : null}
            {candidate.has_relevant_attack_talent ? (
              <Badge variant="secondary">点了{statName(candidate.relevant_attack_stat)}资质</Badge>
            ) : null}
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            {statKeys
              .map((key) => ({ key, value: Number(candidate.individual_talent_distribution[key] ?? 0) }))
              .filter((item) => item.value > 0)
              .map((item) => (
                <Badge key={item.key} variant="secondary" className="bg-slate-100 text-slate-700">
                  {statName(item.key)} {item.value}
                </Badge>
              ))}
          </div>
        </div>
        <Badge variant={candidate.matched_within_tolerance ? "success" : "outline"}>命中</Badge>
      </div>
      <div className="mt-2 text-xs text-muted-foreground">
        预测伤害 {candidate.predicted_damage_value ?? "无法计算"}
      </div>
      {candidate.unknown_factors.length > 0 ? (
        <div className="mt-2 rounded-lg bg-amber-50 px-2 py-1 text-xs text-amber-900">
          未知因素：{candidate.unknown_factors.join("、")}
        </div>
      ) : null}
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
