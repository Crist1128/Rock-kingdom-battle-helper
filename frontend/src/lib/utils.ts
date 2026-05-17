import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import type { ElfDefinitionOut } from "@/types/api";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function safeJsonParse<T>(value: unknown, fallback: T): T {
  if (typeof value !== "string" || value.trim() === "") return fallback;
  try {
    return JSON.parse(value) as T;
  } catch {
    return fallback;
  }
}

export function parseElementTypes(value?: string | null): string[] {
  const parsed = safeJsonParse<unknown>(value ?? "[]", []);
  if (!Array.isArray(parsed)) return [];
  return parsed.filter((item): item is string => typeof item === "string" && item.trim().length > 0);
}

export function elfElementTypes(elf?: Pick<ElfDefinitionOut, "element_types_json"> | null): string[] {
  return parseElementTypes(elf?.element_types_json);
}

export function isDevElf(elf?: Pick<ElfDefinitionOut, "data_version"> | null): boolean {
  return elf?.data_version === "dev";
}

export function filterDevElves<T extends Pick<ElfDefinitionOut, "data_version">>(elves: T[], includeDev = false): T[] {
  return includeDev ? elves : elves.filter((elf) => !isDevElf(elf));
}

export function percentText(value: unknown) {
  if (typeof value !== "number") return "--";
  return `${Math.round(value * 10) / 10}%`;
}

export function statName(key: string) {
  const names: Record<string, string> = {
    hp: "生命",
    physical_attack: "物攻",
    physical_defense: "物防",
    magic_attack: "魔攻",
    magic_defense: "魔防",
    speed: "速度",
  };
  return names[key] ?? key;
}

export function elementTypeName(key?: string | null) {
  /**
   * 后端数据库保存英文内部枚举，前端统一转换为洛克王国中文系别。
   * cleaner.py 当前使用 wing / earth / mechanical / cute / illusion 等内部值；
   * 这里同时兼容早期常见英文别名，避免旧数据或种子数据显示英文。
   */
  const names: Record<string, string> = {
    normal: "普通系",
    fire: "火系",
    water: "水系",
    grass: "草系",
    electric: "电系",
    ice: "冰系",
    wing: "翼系",
    flying: "翼系",
    mechanical: "机械系",
    steel: "机械系",
    earth: "地系",
    ground: "地系",
    ghost: "幽灵系",
    shadow: "幽灵系",
    dragon: "龙系",
    dark: "恶魔系",
    fighting: "武系",
    poison: "毒系",
    light: "光系",
    fairy: "光系",
    cute: "萌系",
    psychic: "萌系",
    illusion: "幻系",
    bug: "虫系",
    "普通": "普通系",
    "火": "火系",
    "水": "水系",
    "草": "草系",
    "电": "电系",
    "冰": "冰系",
    "翼": "翼系",
    "机械": "机械系",
    "地": "地系",
    "幽": "幽灵系",
    "幽灵": "幽灵系",
    "龙": "龙系",
    "恶": "恶魔系",
    "恶魔": "恶魔系",
    "武": "武系",
    "毒": "毒系",
    "光": "光系",
    "萌": "萌系",
    "幻": "幻系",
    "虫": "虫系",
  };
  if (!key) return "未知系别";
  return names[key] ?? key;
}

export function elementTypeNames(keys: string[]) {
  return keys.length > 0 ? keys.map(elementTypeName).join(" / ") : "无系别";
}

export function skillCategoryName(key?: string | null) {
  const names: Record<string, string> = {
    physical: "物理",
    magic: "魔法",
    status: "状态",
    special: "特殊",
  };
  return key ? names[key] ?? key : "未知";
}

export function effectCategoryName(key?: string | null) {
  const names: Record<string, string> = {
    stat_modifier: "属性变化",
    abnormal: "异常",
    special_status: "特殊状态",
    mark: "印记",
    weather: "天气",
    damage_modifier: "伤害修正",
    skill_modifier: "技能修正",
    combo_modifier: "连击修正",
    action_rule: "行动规则",
    resource_rule: "资源规则",
    special_rule: "特殊规则",
  };
  return key ? names[key] ?? key : "未知";
}

export function ownerScopeName(key?: string | null) {
  const names: Record<string, string> = {
    elf: "精灵",
    side: "队伍侧",
    field: "战场",
    skill_slot: "技能槽",
    turn: "当前回合",
  };
  return key ? names[key] ?? key : "未知";
}

export function sideName(side?: string | null) {
  if (side === "self") return "我方";
  if (side === "enemy") return "敌方";
  return "未指定";
}

export function phaseName(phase?: string | null) {
  const names: Record<string, string> = {
    preparation: "准备阶段",
    battle: "战斗中",
    finished: "已结束",
    archived: "已归档",
  };
  return phase ? names[phase] ?? phase : "未知";
}

export function eventTypeName(type?: string | null) {
  const names: Record<string, string> = {
    skill_use: "技能使用",
    damage: "伤害",
    combo_damage: "连击伤害",
    heal: "治疗",
    energy_change: "能量变化",
    effect_apply: "施加状态",
    effect_remove: "移除状态",
    switch_elf: "切换精灵",
    switch_clear: "切换清除",
    weather_change: "天气变化",
    mark_change: "印记变化",
    resource_change: "资源变化",
  };
  return type ? names[type] ?? type : "事件";
}

export function compactId(id?: string | null) {
  if (!id) return "--";
  if (id.length <= 18) return id;
  return `${id.slice(0, 10)}…${id.slice(-6)}`;
}

export function dataVersionName(version?: string | null) {
  if (!version) return "unknown";
  if (version === "rocom_bwiki_mvp_full") return "BWIKI 全量";
  if (version === "dev") return "dev 示例";
  return version;
}

export function formatTalentPattern(pattern?: string | null) {
  if (!pattern) return "无";
  return pattern
    .replace(/physical_attack/g, "物攻")
    .replace(/physical_defense/g, "物防")
    .replace(/magic_attack/g, "魔攻")
    .replace(/magic_defense/g, "魔防")
    .replace(/speed/g, "速度")
    .replace(/hp/g, "生命");
}
