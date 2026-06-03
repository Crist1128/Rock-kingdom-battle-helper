import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { compactId, eventTypeName, sideName } from "@/lib/utils";

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
        <CardTitle>事件时间线</CardTitle>
        <Button variant="outline" size="sm" onClick={() => refetch()} disabled={!battleId}>刷新</Button>
      </CardHeader>
      <CardContent>
        {!battleId ? <div className="text-sm text-muted-foreground">尚未选择战斗。</div> : null}
        {isLoading ? <div className="text-sm text-muted-foreground">加载中...</div> : null}
        {battleId && data.length === 0 ? <div className="text-sm text-muted-foreground">暂无事件。</div> : null}
        <div className={compact ? "max-h-96 space-y-3 overflow-y-auto" : "space-y-5"}>
          {data.map((turn) => (
            <div key={turn.turn_number}>
              <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
                <span>第 {turn.turn_number} 回合</span>
                <Badge variant="outline">{turn.events.length} 事件</Badge>
              </div>
              <div className="space-y-2">
                {turn.events.map((item) => (
                  <div
                    key={item.event.event_id}
                    className={selectedEventId === item.event.event_id ? "rounded-2xl border border-primary bg-white p-3" : "rounded-2xl border bg-white p-3"}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="font-medium">{eventTypeName(item.event.event_type)}</div>
                      <Badge variant={item.detail_type ? "default" : "secondary"}>{item.detail_type ?? "generic"}</Badge>
                    </div>
                    <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                      <span>事件：{compactId(item.event.event_id)}</span>
                      <span>行动：{sideName(item.event.actor_side)} / {compactId(item.event.actor_elf_id)}</span>
                      <span>目标：{sideName(item.event.target_side)} / {compactId(item.event.target_elf_id)}</span>
                      <span>技能：{compactId(item.event.skill_id)}</span>
                      <span>快照：{compactId(item.event.snapshot_id)}</span>
                    </div>
                    {!compact ? (
                      <div className="mt-2 flex flex-wrap gap-2">
                        {onSelectEvent ? (
                          <Button variant="outline" size="sm" onClick={() => onSelectEvent(item.event.event_id)}>
                            选择事件
                          </Button>
                        ) : null}
                        {item.event.snapshot_id ? (
                          <Button variant="ghost" size="sm" onClick={() => setSnapshotId(item.event.snapshot_id ?? null)}>
                            查看快照
                          </Button>
                        ) : null}
                      </div>
                    ) : null}
                    {item.event.notes ? <div className="mt-2 text-xs">备注：{item.event.notes}</div> : null}
                    {!compact && item.event.payload_json ? (
                      <pre className="mt-2 max-h-40 overflow-auto rounded-xl bg-slate-50 p-2 text-xs text-muted-foreground">
                        {formatJsonText(item.event.payload_json)}
                      </pre>
                    ) : null}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
        {!compact && snapshotId ? (
          <div className="mt-5 rounded-2xl border bg-white p-3">
            <div className="mb-2 flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-semibold">快照详情</div>
                <div className="text-xs text-muted-foreground">{snapshotId}</div>
              </div>
              <Button variant="ghost" size="sm" onClick={() => setSnapshotId(null)}>关闭</Button>
            </div>
            {snapshotQuery.isLoading ? <div className="text-sm text-muted-foreground">读取快照中...</div> : null}
            {snapshotQuery.error ? (
              <div className="rounded-xl border border-red-200 bg-red-50 p-2 text-xs text-red-700">
                快照读取失败：{String((snapshotQuery.error as Error).message)}
              </div>
            ) : null}
            {snapshotQuery.data ? (
              <div className="space-y-3 text-xs">
                <div className="grid grid-cols-3 gap-2">
                  <SnapshotMetric label="回合" value={snapshotQuery.data.turn_number} />
                  <SnapshotMetric label="我方上场" value={compactId(snapshotQuery.data.self_active_elf_id)} />
                  <SnapshotMetric label="敌方上场" value={compactId(snapshotQuery.data.enemy_active_elf_id)} />
                </div>
                <pre className="max-h-72 overflow-auto rounded-xl bg-slate-50 p-3 text-muted-foreground">
                  {formatJsonText(snapshotQuery.data.full_snapshot_json ?? "[]")}
                </pre>
              </div>
            ) : null}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function SnapshotMetric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-xl border bg-slate-50 p-2">
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
