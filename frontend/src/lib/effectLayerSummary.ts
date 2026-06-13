import type { EffectDefinitionOut } from "@/types/api";

type JsonRecord = Record<string, unknown>;

export interface EffectLayerSummary {
  layerText: string;
  ruleTexts: string[];
  finalTexts: string[];
  displayName?: string;
  hasStructuredRule: boolean;
}

const STAT_NAMES: Record<string, string> = {
  hp: "生命",
  physical_attack: "物攻",
  physical_defense: "物防",
  magic_attack: "魔攻",
  magic_defense: "魔防",
  speed: "速度",
};

function asRecord(value: unknown): JsonRecord | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as JsonRecord)
    : null;
}

function parseRule(value: unknown): JsonRecord | null {
  if (!value) return null;
  if (typeof value === "string") {
    try {
      return asRecord(JSON.parse(value));
    } catch {
      return null;
    }
  }
  return asRecord(value);
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function signedNumber(value: number, unit = ""): string {
  const rounded = Math.round(value * 1000) / 1000;
  const abs = Math.abs(rounded);
  const text = Number.isInteger(abs) ? String(abs) : String(abs);
  return `${rounded >= 0 ? "+" : "-"}${text}${unit}`;
}

function signedLayer(value: number): string {
  return signedNumber(value, "层");
}

function signedPercent(value: number): string {
  return signedNumber(value * 100, "%");
}

function multiplierText(value: number): string {
  const rounded = Math.round(value * 1000) / 1000;
  return `×${Number.isInteger(rounded) ? String(rounded) : String(rounded)}`;
}

function modifierList(rule: JsonRecord | null): JsonRecord[] {
  if (!rule) return [];
  const modifiers = rule.modifiers;
  if (Array.isArray(modifiers)) {
    return modifiers.map(asRecord).filter((item): item is JsonRecord => item !== null);
  }
  return [rule];
}

function statModifierTexts(rule: JsonRecord | null, layers: number) {
  const ruleTexts: string[] = [];
  const finalTexts: string[] = [];
  const targetNames: string[] = [];
  const equivalentLayerTexts: string[] = [];
  let hasPerLayerRule = false;

  for (const modifier of modifierList(rule)) {
    const stat = typeof modifier.stat === "string" ? modifier.stat : "";
    const label = STAT_NAMES[stat] ?? stat;
    if (!label) continue;
    targetNames.push(label);

    const valuePerLayer = asNumber(modifier.value_per_layer);
    const fixedValue = asNumber(modifier.value);
    const valueType = typeof modifier.value_type === "string" ? modifier.value_type : "";
    const isPercent = valueType === "percent_add";
    const isFlat = valueType === "flat_add" || modifier.modifier_type === "flat_speed";

    if (valuePerLayer !== null) {
      hasPerLayerRule = true;
      const finalValue = valuePerLayer * layers;
      if (isPercent) {
        ruleTexts.push(`${label}每层 ${signedPercent(valuePerLayer)}`);
        finalTexts.push(`${label} ${signedPercent(finalValue)}`);
      } else if (isFlat) {
        ruleTexts.push(`${label}每层 ${signedNumber(valuePerLayer)}`);
        finalTexts.push(`${label} ${signedNumber(finalValue)}`);
      }
    } else if (fixedValue !== null) {
      if (isPercent) {
        const equivalentLayers = fixedValue / 0.1;
        equivalentLayerTexts.push(`${label} ${signedLayer(equivalentLayers)}`);
        ruleTexts.push(`${label}固定 ${signedPercent(fixedValue)}（等价 ${signedLayer(equivalentLayers)}）`);
        finalTexts.push(`${label} ${signedPercent(fixedValue)}`);
      } else if (isFlat || modifier.modifier_type === "flat_add") {
        const equivalentLayers = stat === "speed" ? fixedValue / 10 : null;
        if (equivalentLayers !== null) {
          equivalentLayerTexts.push(`${label} ${signedLayer(equivalentLayers)}`);
        }
        ruleTexts.push(
          equivalentLayers !== null
            ? `${label}固定 ${signedNumber(fixedValue)}（等价 ${signedLayer(equivalentLayers)}）`
            : `${label}固定 ${signedNumber(fixedValue)}`,
        );
        finalTexts.push(`${label} ${signedNumber(fixedValue)}`);
      }
    }
  }

  return { ruleTexts, finalTexts, targetNames, equivalentLayerTexts, hasPerLayerRule };
}

function skillModifierTexts(rule: JsonRecord | null, layers: number) {
  const ruleTexts: string[] = [];
  const finalTexts: string[] = [];
  const targetNames: string[] = [];

  if (!rule) return { ruleTexts, finalTexts, targetNames };

  const energyDelta = asNumber(rule.energy_cost_delta_per_layer);
  if (energyDelta !== null) {
    targetNames.push("能耗");
    ruleTexts.push(`能耗每层 ${signedNumber(energyDelta)}`);
    finalTexts.push(`能耗 ${signedNumber(energyDelta * layers)}`);
  }

  const hitCountDelta = asNumber(rule.hit_count_delta_per_layer);
  if (hitCountDelta !== null) {
    targetNames.push("连击");
    ruleTexts.push(`连击每层 ${signedNumber(hitCountDelta)}`);
    finalTexts.push(`连击 ${signedNumber(hitCountDelta * layers)}`);
  }

  const powerAdd = asNumber(rule.power_add_per_layer);
  if (powerAdd !== null) {
    const prefix = rule.modifier_type === "burst_power_add" ? "迸发威力" : "威力";
    targetNames.push(prefix);
    ruleTexts.push(`${prefix}每层 ${signedNumber(powerAdd)}`);
    finalTexts.push(`${prefix} ${signedNumber(powerAdd * layers)}`);
  }

  const powerMultiplier = asNumber(rule.power_multiplier_add_per_layer);
  if (powerMultiplier !== null) {
    targetNames.push("威力倍率");
    ruleTexts.push(`威力倍率每层 ${signedPercent(powerMultiplier)}`);
    finalTexts.push(`威力倍率 ${signedPercent(powerMultiplier * layers)}`);
  }

  const fixedDamageBonus = asNumber(rule.value);
  if (rule.modifier_type === "damage_bonus" && fixedDamageBonus !== null) {
    const element = typeof rule.element_type === "string" ? `${rule.element_type}系` : "";
    targetNames.push(`${element}伤害`);
    ruleTexts.push(`${element}伤害固定 ${signedPercent(fixedDamageBonus)}`);
    finalTexts.push(`${element}伤害 ${signedPercent(fixedDamageBonus)}`);
  }

  const fixedCostMultiplier = asNumber(rule.value);
  if (rule.modifier_type === "cost_multiplier" && fixedCostMultiplier !== null) {
    const element = typeof rule.element_type === "string" ? `${rule.element_type}系` : "";
    targetNames.push(`${element}能耗`);
    ruleTexts.push(`${element}能耗固定 ${multiplierText(fixedCostMultiplier)}`);
    finalTexts.push(`${element}能耗 ${multiplierText(fixedCostMultiplier)}`);
  }

  return { ruleTexts, finalTexts, targetNames };
}

function buildDisplayName(definition: EffectDefinitionOut | undefined, targetNames: string[]) {
  if (!definition || targetNames.length === 0) return undefined;
  const uniqueTargets = Array.from(new Set(targetNames));
  const rawName = definition.effect_name;
  const looksLikeValueName = /[+-]\d/.test(rawName) || rawName.includes("×");
  if (!looksLikeValueName) return rawName;
  return `${uniqueTargets.join("/")}修正`;
}

export function buildEffectLayerSummary(
  definition: EffectDefinitionOut | undefined,
  layersInput: number | null | undefined,
): EffectLayerSummary {
  const layers = Math.max(1, Number(layersInput ?? definition?.default_layers ?? 1) || 1);
  const statTexts = statModifierTexts(parseRule(definition?.stat_modifier_json), layers);
  const skillTexts = skillModifierTexts(parseRule(definition?.skill_modifier_json), layers);
  const ruleTexts = [...statTexts.ruleTexts, ...skillTexts.ruleTexts];
  const finalTexts = [...statTexts.finalTexts, ...skillTexts.finalTexts];
  const targetNames = [...statTexts.targetNames, ...skillTexts.targetNames];
  const equivalentLayerValues = Array.from(
    new Set(statTexts.equivalentLayerTexts.map((text) => text.replace(/^.+ /, ""))),
  );
  const layerText = !statTexts.hasPerLayerRule && equivalentLayerValues.length > 0
    ? equivalentLayerValues.length === 1
      ? `等价 ${equivalentLayerValues[0]}`
      : "固定修正"
    : `层数 ${layers}`;

  return {
    layerText,
    ruleTexts,
    finalTexts,
    displayName: buildDisplayName(definition, targetNames),
    hasStructuredRule: ruleTexts.length > 0 || finalTexts.length > 0,
  };
}
