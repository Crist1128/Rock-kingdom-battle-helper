import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { compactId, eventTypeName, sideName } from "@/lib/utils";

export function EventTimeline({ battleId, compact = false }: { battleId?: string | null; compact?: boolean }) {
  const { data = [], isLoading, refetch } = useQuery({
    queryKey: ["timeline", battleId],
    queryFn: () => api.battles.timeline(battleId!),
    enabled: Boolean(battleId),
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
                  <div key={item.event.event_id} className="rounded-2xl border bg-white p-3">
                    <div className="flex items-center justify-between gap-3">
                      <div className="font-medium">{eventTypeName(item.event.event_type)}</div>
                      <Badge variant={item.detail_type ? "default" : "secondary"}>{item.detail_type ?? "generic"}</Badge>
                    </div>
                    <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                      <span>行动：{sideName(item.event.actor_side)} / {compactId(item.event.actor_elf_id)}</span>
                      <span>目标：{sideName(item.event.target_side)} / {compactId(item.event.target_elf_id)}</span>
                      <span>技能：{compactId(item.event.skill_id)}</span>
                      <span>快照：{compactId(item.event.snapshot_id)}</span>
                    </div>
                    {item.event.notes ? <div className="mt-2 text-xs">备注：{item.event.notes}</div> : null}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
