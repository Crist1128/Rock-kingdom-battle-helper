import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useAppStore } from "@/store/useAppStore";
import { EventTimeline } from "@/components/EventTimeline";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";

export function EventLogPage() {
  const { currentBattleId, setCurrentBattleId } = useAppStore();
  const [battleIdInput, setBattleIdInput] = useState(currentBattleId ?? "");
  const [eventIdInput, setEventIdInput] = useState("");
  const [lastMessage, setLastMessage] = useState<string | null>(null);
  const voidMutation = useMutation({
    mutationFn: () => api.battles.voidEvent(currentBattleId!, eventIdInput.trim(), { reason: "manual_void" }),
    onSuccess: () => setLastMessage("事件已作废；时间线刷新后将不再显示原事件。"),
  });
  const replayMutation = useMutation({
    mutationFn: () => api.battles.replayFrom(currentBattleId!, eventIdInput.trim()),
    onSuccess: (result) => setLastMessage(result.message),
  });
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">事件日志与回放</h1>
        <p className="mt-1 text-muted-foreground">查看时间线，并使用后端提供的事件作废与重放占位接口。</p>
      </div>
      <Card>
        <CardContent className="flex items-end gap-3 pt-5">
          <div className="flex-1"><label className="text-sm font-medium">battle_id</label><Input value={battleIdInput} onChange={(e) => setBattleIdInput(e.target.value)} /></div>
          <Button onClick={() => setCurrentBattleId(battleIdInput.trim())}>切换</Button>
        </CardContent>
      </Card>
      <div className="grid grid-cols-[1fr_360px] gap-6">
        <EventTimeline battleId={currentBattleId} />
        <Card>
          <CardHeader>
            <CardTitle>纠错能力</CardTitle>
            <CardDescription>事件作废接口已接入；重放接口当前返回明确占位，不会执行真实重算。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div>
              <label className="text-sm font-medium">event_id</label>
              <Input value={eventIdInput} onChange={(e) => setEventIdInput(e.target.value)} placeholder="从时间线复制 event_id" />
            </div>
            <Button className="w-full" variant="destructive" disabled={!currentBattleId || !eventIdInput.trim() || voidMutation.isPending} onClick={() => voidMutation.mutate()}>作废事件</Button>
            <Button className="w-full" variant="outline" disabled={!currentBattleId || !eventIdInput.trim() || replayMutation.isPending} onClick={() => replayMutation.mutate()}>从该事件开始重放</Button>
            <div className="rounded-2xl border bg-white p-3"><Badge variant="warning">占位</Badge><div className="mt-2">修正事件接口已存在，但通用修正表单较复杂，当前页面先保留作废和重放入口。</div></div>
            {lastMessage ? <div className="rounded-2xl border bg-emerald-50 p-3 text-emerald-900">{lastMessage}</div> : null}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
