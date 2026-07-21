import { cn } from "@/lib/utils";

/**
 * 能量格：一个能量值对应一个发光菱形点，上限 99 点，超出按 99 显示。
 * 点数较多时自动换行。
 */
export function EnergyPips({
  value,
  max = 99,
  compact = false,
  className,
}: {
  value?: number | null;
  max?: number;
  compact?: boolean;
  className?: string;
}) {
  const energy = typeof value === "number" && Number.isFinite(value) ? Math.max(0, Math.floor(value)) : 0;
  const shown = Math.min(energy, max);

  return (
    <span className={cn("inline-flex items-center gap-1", className)} title={`能量 ${energy}`}>
      <span className={cn("font-medium tracking-wide text-muted-foreground", compact ? "text-[10px]" : "text-xs")}>
        能量
      </span>
      <span className="inline-flex max-w-full flex-wrap items-center gap-[3px]">
        {shown > 0 ? (
          Array.from({ length: shown }, (_, index) => (
            <span
              key={index}
              className={cn(
                "rotate-45 rounded-[2px] bg-gradient-to-br from-primary to-info shadow-glow-sm",
                compact ? "h-1.5 w-1.5" : "h-2 w-2",
              )}
            />
          ))
        ) : (
          <span className={cn("rotate-45 rounded-[2px] border border-muted-foreground/40", compact ? "h-1.5 w-1.5" : "h-2 w-2")} />
        )}
      </span>
      <span className={cn("font-num font-semibold text-foreground", compact ? "text-[10px]" : "text-xs")}>
        {energy}
      </span>
    </span>
  );
}
