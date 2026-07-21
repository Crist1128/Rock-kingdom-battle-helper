import { useState } from "react";
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn, compactId, eventTypeName, sideName } from "@/lib/utils";
import type { BattleEffectSnapshotOut, BattleEventOut, BattleTimelineTurnOut, Side } from "@/types/api";

export function EventTimeline({
  battleId,
  compact = false,
  onSelectEvent,
  selectedEventId,
}: {
  battleId?: string | null;
  compact?: boolean;
  onSelectEvent?: (eventId: string) => void;
  selectedEventId?: string | null;
}) {
  const [snapshotId, setSnapshotId] = useState<string | null>(null);
  const { data = [], isLoading, refetch } = useQuery({
    queryKey: ["timeline", battleId],
    queryFn: () => api.battles.timeline(battleId!),
    enabled: Boolean(battleId),
  });
  const snapshotQuery = useQuery({
    queryKey: ["snapshot", battleId, snapshotId],
    queryFn: () => api.battles.snapshot(battleId!, snapshotId!),
    enabled: Boolean(battleId && snapshotId),
  });

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>{compact ? "战斗日志" : "事件时间线"}</CardTitle>
        <Button variant="outline" size="sm" onClick={() => refetch()} disabled={!battleId}>刷新</Button>
      </CardHeader>
      <CardContent>
        {!battleId ? <div className="text-sm text-muted-foreground">尚未选择战斗。</div> : null}
        {isLoading ? <div className="text-sm text-muted-foreground">加载中...</div> : null}
        {battleId && data.length === 0 ? <div className="text-sm text-muted-foreground">暂无事件。</div> : null}
        {compact ? (
          <CombatLog turns={data} />
        ) : (
          <FullTimeline
            turns={data}
            selectedEventId={selectedEventId}
            onSelectEvent={onSelectEvent}
            onShowSnapshot={setSnapshotId}
          />
        )}
        {!compact && snapshotId ? (
          <SnapshotPanel
            snapshotId={snapshotId}
            onClose={() => setSnapshotId(null)}
            query={snapshotQuery}
          />
        ) : null}
      </CardContent>
    </Card>
  );
}

type SnapshotQueryResult = UseQueryResult<BattleEffectSnapshotOut>;

/** 终端风战斗日志：等宽字体、行式布局、我方青 / 敌方红前缀。 */
function CombatLog({ turns }: { turns: BattleTimelineTurnOut[] }) {
  return (
    <div className="max-h-96 overflow-y-auto rounded-lg border border-border/70 bg-background/70 p-2 font-num text-[11px] leading-5">
      {turns.map((turn) => (
        <div key={turn.turn_number}>
          <div className="mt-1.5 flex items-center gap-2 px-1.5 text-[10px] text-muted-foreground first:mt-0">
            <span className="shrink-0">T{turn.turn_number}</span>
            <span className="h-px flex-1 bg-border/70" />
            <span className="shrink-0">{turn.events.length} 事件</span>
          </div>
          {turn.events.map((item) => (
            <CombatLogRow key={item.event.event_id} event={item.event} />
          ))}
        </div>
      ))}
    </div>
  );
}

function CombatLogRow({ event }: { event: BattleEventOut }) {
  const side = event.actor_side as Side | null | undefined;
  const sideClass =
    side === "self" ? "text-self" : side === "enemy" ? "text-enemy" : "text-muted-foreground";
  const prefix = side === "self" ? "▸" : side === "enemy" ? "◂" : "·";
  const payload = parsePayload(event.payload_json);
  const ruleConflicts = Array.isArray(payload.rule_conflicts)
    ? payload.rule_conflicts.filter(isRecord)
    : [];

  return (
    <div className="rounded px-1.5 py-0.5 transition-colors hover:bg-raised/50">
      <div className="flex items-baseline gap-2">
        <span className={cn("w-3 shrink-0", sideClass)}>{prefix}</span>
        <span className="shrink-0 font-semibold text-foreground">
          {eventTypeName(event.event_type)}
        </span>
        <span className="min-w-0 truncate text-muted-foreground">
          {sideName(event.actor_side)}
          {event.target_side || event.target_elf_id ? ` → ${sideName(event.target_side)}` : ""}
          {event.skill_id ? ` · ${compactId(event.skill_id)}` : ""}
        </span>
        {event.notes ? (
          <span className="ml-auto shrink-0 truncate text-muted-foreground/70" title={event.notes}>
            {event.notes}
          </span>
        ) : null}
      </div>
      {ruleConflicts.length > 0 ? (
        <div className="ml-5 text-warning">
          规则冲突：
          {ruleConflicts
            .map((conflict) => String(conflict.message ?? conflict.conflict_type ?? "未知冲突"))
            .join("；")}
        </div>
      ) : null}
    </div>
  );
}

function FullTimeline({
  turns,
  selectedEventId,
  onSelectEvent,
  onShowSnapshot,
}: {
  turns: BattleTimelineTurnOut[];
  selectedEventId?: string | null;
  onSelectEvent?: (eventId: string) => void;
  onShowSnapshot: (snapshotId: string | null) => void;
}) {
  return (
    <div className="space-y-5">
      {turns.map((turn) => (
        <div key={turn.turn_number}>
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
            <span>第 {turn.turn_number} 回合</span>
            <Badge variant="outline">{turn.events.length} 事件</Badge>
          </div>
          <div className="space-y-2">
            {turn.events.map((item) => {
              const payload = parsePayload(item.event.payload_json);
              const ruleConflicts = Array.isArray(payload.rule_conflicts)
                ? payload.rule_conflicts.filter(isRecord)
                : [];
              return (
                <div
                  key={item.event.event_id}
                  className={cn(
                    "rounded-xl border bg-raised/40 p-3",
                    selectedEventId === item.event.event_id && "border-primary",
                  )}
                >
                  <div className="flex items-center justify-between gap-3">
                    <div className="font-medium">{eventTypeName(item.event.event_type)}</div>
                    <Badge variant={item.detail_type ? "default" : "secondary"}>
                      {item.detail_type ?? "generic"}
                    </Badge>
                  </div>
                  <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                    <span>事件：{compactId(item.event.event_id)}</span>
                    <span>行动：{sideName(item.event.actor_side)} / {compactId(item.event.actor_elf_id)}</span>
                    <span>目标：{sideName(item.event.target_side)} / {compactId(item.event.target_elf_id)}</span>
                    <span>技能：{compactId(item.event.skill_id)}</span>
                    <span>快照：{compactId(item.event.snapshot_id)}</span>
                  </div>
                  {ruleConflicts.length > 0 ? (
                    <div className="mt-2 rounded-lg border border-warning/25 bg-warning/10 p-2 text-xs text-warning">
                      规则冲突：
                      {ruleConflicts
                        .map((conflict) => String(conflict.message ?? conflict.conflict_type ?? "未知冲突"))
                        .join("；")}
                    </div>
                  ) : null}
                  <div className="mt-2 flex flex-wrap gap-2">
                    {onSelectEvent ? (
                      <Button variant="outline" size="sm" onClick={() => onSelectEvent(item.event.event_id)}>
                        选择事件
                      </Button>
                    ) : null}
                    {item.event.snapshot_id ? (
                      <Button variant="ghost" size="sm" onClick={() => onShowSnapshot(item.event.snapshot_id ?? null)}>
                        查看快照
                      </Button>
                    ) : null}
                  </div>
                  {item.event.notes ? <div className="mt-2 text-xs">备注：{item.event.notes}</div> : null}
                  {item.event.payload_json ? (
                    <pre className="mt-2 max-h-40 overflow-auto rounded-lg bg-raised/60 p-2 text-xs text-muted-foreground">
                      {formatJsonText(item.event.payload_json)}
                    </pre>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

function SnapshotPanel({
  snapshotId,
  onClose,
  query,
}: {
  snapshotId: string;
  onClose: () => void;
  query: SnapshotQueryResult;
}) {
  return (
    <div className="mt-5 rounded-xl border bg-raised/40 p-3">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-semibold">快照详情</div>
          <div className="font-num text-xs text-muted-foreground">{snapshotId}</div>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose}>关闭</Button>
      </div>
      {query.isLoading ? <div className="text-sm text-muted-foreground">读取快照中...</div> : null}
      {query.error ? (
        <div className="rounded-lg border border-destructive/25 bg-destructive/10 p-2 text-xs text-destructive">
          快照读取失败：{String((query.error as Error).message)}
        </div>
      ) : null}
      {query.data ? (
        <div className="space-y-3 text-xs">
          <div className="grid grid-cols-3 gap-2">
            <SnapshotMetric label="回合" value={query.data.turn_number} />
            <SnapshotMetric label="我方上场" value={compactId(query.data.self_active_elf_id)} />
            <SnapshotMetric label="敌方上场" value={compactId(query.data.enemy_active_elf_id)} />
          </div>
          <pre className="max-h-72 overflow-auto rounded-lg bg-raised/60 p-3 text-muted-foreground">
            {formatJsonText(query.data.full_snapshot_json ?? "[]")}
          </pre>
        </div>
      ) : null}
    </div>
  );
}

function SnapshotMetric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border bg-raised/60 p-2">
      <div className="text-muted-foreground">{label}</div>
      <div className="mt-1 font-medium">{value}</div>
    </div>
  );
}

function formatJsonText(value: string) {
  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    return value;
  }
}

function parsePayload(value?: string | null): Record<string, unknown> {
  if (!value) return {};
  try {
    const parsed = JSON.parse(value) as unknown;
    return isRecord(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
