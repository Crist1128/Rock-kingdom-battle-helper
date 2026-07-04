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

  return (
    <div className={cn("space-y-1", compact ? "text-[10px]" : "text-xs", className)}>
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium text-slate-700">HP</span>
        <span className="shrink-0 font-semibold text-slate-950">
          {displayedCurrent ?? "--"} / {displayedMax ?? "--"}
          <span className="ml-1 text-muted-foreground">
            ({displayedPercent == null ? "--" : displayedPercent}%)
          </span>
        </span>
      </div>
      <div className={cn("overflow-hidden rounded-full bg-slate-200", compact ? "h-2" : "h-3")}>
        <div
          className="h-full rounded-full bg-emerald-300 transition-[width] duration-300"
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
