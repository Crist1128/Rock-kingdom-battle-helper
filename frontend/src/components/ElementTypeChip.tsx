import { elementTypeColor } from "@/lib/elementTypeColors";
import { cn, elementTypeName } from "@/lib/utils";

/**
 * 系别极简 chip：专属色点 + 系别名。
 * 替代原来灰扑扑的 outline Badge，是全局统一的系别展示方式。
 */
export function ElementTypeChip({
  type,
  className,
  showName = true,
}: {
  type?: string | null;
  className?: string;
  showName?: boolean;
}) {
  const color = elementTypeColor(type);
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs text-muted-foreground", className)}>
      <span
        className="h-2 w-2 shrink-0 rounded-full"
        style={{ backgroundColor: color, boxShadow: `0 0 6px color-mix(in srgb, ${color} 45%, transparent)` }}
      />
      {showName ? <span style={{ color }}>{elementTypeName(type)}</span> : null}
    </span>
  );
}
