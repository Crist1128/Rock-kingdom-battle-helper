import { canonicalElementType } from "@/lib/utils";

/**
 * 18 个系别的专属色（CSS 变量引用，随深浅主题切换，见 styles.css 的 --el-* 定义）。
 * 全局统一从 canonicalElementType 归一化后的英文 key 取色。
 */
const ELEMENT_TYPE_VAR_NAMES: Record<string, string> = {
  normal: "--el-normal",
  fire: "--el-fire",
  water: "--el-water",
  grass: "--el-grass",
  electric: "--el-electric",
  ice: "--el-ice",
  wing: "--el-wing",
  mechanical: "--el-mechanical",
  earth: "--el-earth",
  ghost: "--el-ghost",
  dragon: "--el-dragon",
  dark: "--el-dark",
  fighting: "--el-fighting",
  poison: "--el-poison",
  light: "--el-light",
  cute: "--el-cute",
  illusion: "--el-illusion",
  bug: "--el-bug",
};

const FALLBACK_COLOR = "hsl(var(--muted-foreground))";

/** 取系别专属色（var() 引用）；未知系别返回中性色。 */
export function elementTypeColor(type?: string | null): string {
  const canonical = canonicalElementType(type);
  const varName = canonical ? ELEMENT_TYPE_VAR_NAMES[canonical] : undefined;
  return varName ? `var(${varName})` : FALLBACK_COLOR;
}
