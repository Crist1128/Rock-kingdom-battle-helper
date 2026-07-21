import { cn } from "@/lib/utils";

interface HealthBarProps {
  currentHpValue?: number | null;
  currentHpPercent?: number | null;
  maxHp?: number | null;
  sourceLabel?: string | null;
  compact?: boolean;
  className?: string;
}

export function HealthBar({
  currentHpValue,
  currentHpPercent,
  maxHp,
  sourceLabel,
  compact = false,
  className,
}: HealthBarProps) {
  const percent = normalizePercent(currentHpPercent);
  const maxHpValue = normalizePositiveNumber(maxHp);
  const displayedCurrent = resolveCurrentHp(currentHpValue, percent, maxHpValue);
  const displayedMax = maxHpValue == null ? null : Math.ceil(maxHpValue);
  const displayedPercent = percent == null ? null : Math.ceil(percent);
  const barWidth = percent == null ? 0 : percent;

  const fillClass =
    percent == null
      ? "bg-raised"
      : percent > 50
        ? "bg-gradient-to-r from-emerald-400 to-teal-300"
        : percent > 20
          ? "bg-gradient-to-r from-amber-400 to-yellow-300"
          : "bg-gradient-to-r from-rose-500 to-red-400";

  return (
    <div className={cn("space-y-1", compact ? "text-[10px]" : "text-xs", className)}>
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium tracking-wide text-muted-foreground">HP</span>
        <span className="font-num shrink-0 font-semibold text-foreground">
          {displayedCurrent ?? "--"}
          <span className="text-muted-foreground"> / {displayedMax ?? "--"}</span>
          <span className="ml-1 text-muted-foreground">
            ({displayedPercent == null ? "--" : displayedPercent}%)
          </span>
        </span>
      </div>
      <div
        className={cn(
          "overflow-hidden rounded-full bg-raised/80 shadow-[0_1px_2px_0_hsl(0_0%_0%/0.4)_inset]",
          compact ? "h-1.5" : "h-2.5",
        )}
      >
        <div
          className={cn("h-full rounded-full transition-[width] duration-300", fillClass)}
          style={{ width: `${barWidth}%` }}
        />
      </div>
      {sourceLabel ? <div className="truncate text-[11px] text-muted-foreground">{sourceLabel}</div> : null}
    </div>
  );
}

function normalizePercent(value?: number | null): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return Math.min(Math.max(value, 0), 100);
}

function normalizePositiveNumber(value?: number | null): number | null {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) return null;
  return value;
}

function resolveCurrentHp(
  currentHpValue: number | null | undefined,
  percent: number | null,
  maxHp: number | null,
): number | null {
  if (typeof currentHpValue === "number" && Number.isFinite(currentHpValue)) {
    return Math.ceil(Math.max(currentHpValue, 0));
  }
  if (percent == null || maxHp == null) return null;
  return Math.ceil(maxHp * percent / 100);
}
