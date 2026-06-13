import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useAppStore } from "@/store/useAppStore";
import { EventTimeline } from "@/components/EventTimeline";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";

export function EventLogPage() {
  const queryClient = useQueryClient();
  const { currentBattleId, setCurrentBattleId } = useAppStore();
  const [battleIdInput, setBattleIdInput] = useState(currentBattleId ?? "");
  const [eventIdInput, setEventIdInput] = useState("");
  const [correctionTurn, setCorrectionTurn] = useState(1);
  const [correctionType, setCorrectionType] = useState("manual_correction");
  const [correctionNotes, setCorrectionNotes] = useState("");
  const [lastMessage, setLastMessage] = useState<string | null>(null);
  const refreshTimeline = () => queryClient.invalidateQueries({ queryKey: ["timeline", currentBattleId] });
  const voidMutation = useMutation({
    mutationFn: () => api.battles.voidEvent(currentBattleId!, eventIdInput.trim(), { reason: "manual_void" }),
    onSuccess: () => {
      refreshTimeline();
      setLastMessage("事件已作废；时间线刷新后将不再显示原事件。");
    },
  });
  const replayMutation = useMutation({
    mutationFn: () => api.battles.replayFrom(currentBattleId!, eventIdInput.trim()),
    onSuccess: (result) => setLastMessage(result.message),
  });
  const correctMutation = useMutation({
    mutationFn: () => api.battles.correctEvent(currentBattleId!, eventIdInput.trim(), {
      replacement_event: {
        turn_number: correctionTurn,
        event_type: correctionType,
        source: "manual_input",
        manual_override: true,
        notes: correctionNotes,
      },
      reason: correctionNotes || "manual_correct",
      void_original: true,
    }),
    onSuccess: (event) => {
      refreshTimeline();
      setLastMessage(`已创建修正事件：${event.event_id}`);
    },
  });
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">事件日志与回放</h1>
        <p className="mt-1 text-muted-foreground">查看时间线，并使用后端提供的事件作废与重放接口。</p>
      </div>
      <Card>
        <CardContent className="flex items-end gap-3 pt-5">
          <div className="flex-1"><label className="text-sm font-medium">battle_id</label><Input value={battleIdInput} onChange={(e) => setBattleIdInput(e.target.value)} /></div>
          <Button onClick={() => setCurrentBattleId(battleIdInput.trim())}>切换</Button>
        </CardContent>
      </Card>
      <div className="grid grid-cols-[1fr_360px] gap-6">
        <EventTimeline
          battleId={currentBattleId}
          selectedEventId={eventIdInput}
          onSelectEvent={(eventId) => setEventIdInput(eventId)}
        />
        <Card>
          <CardHeader>
            <CardTitle>纠错能力</CardTitle>
            <CardDescription>事件作废接口已接入；重放接口会重建实时估计、运行时状态和事件后快照链。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div>
              <label className="text-sm font-medium">event_id</label>
              <Input value={eventIdInput} onChange={(e) => setEventIdInput(e.target.value)} placeholder="从时间线复制 event_id" />
            </div>
            <Button className="w-full" variant="destructive" disabled={!currentBattleId || !eventIdInput.trim() || voidMutation.isPending} onClick={() => voidMutation.mutate()}>作废事件</Button>
            <Button className="w-full" variant="outline" disabled={!currentBattleId || !eventIdInput.trim() || replayMutation.isPending} onClick={() => replayMutation.mutate()}>从该事件开始重放</Button>
            <div className="rounded-2xl border bg-white p-3">
              <div className="mb-2 flex items-center gap-2">
                <Badge variant="outline">通用修正</Badge>
                <span className="text-xs text-muted-foreground">创建替代事件并作废原事件</span>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-sm font-medium">回合</label>
                  <Input type="number" value={correctionTurn} onChange={(e) => setCorrectionTurn(Number(e.target.value))} />
                </div>
                <div>
                  <label className="text-sm font-medium">事件类型</label>
                  <Input value={correctionType} onChange={(e) => setCorrectionType(e.target.value)} />
                </div>
              </div>
              <div className="mt-2">
                <label className="text-sm font-medium">修正说明</label>
                <Input value={correctionNotes} onChange={(e) => setCorrectionNotes(e.target.value)} placeholder="例如：原识别有误，改为手动修正事件" />
              </div>
              <Button className="mt-3 w-full" variant="secondary" disabled={!currentBattleId || !eventIdInput.trim() || correctMutation.isPending} onClick={() => correctMutation.mutate()}>
                {correctMutation.isPending ? "修正中..." : "创建修正事件"}
              </Button>
            </div>
            <div className="rounded-2xl border bg-white p-3"><Badge variant="success">可用</Badge><div className="mt-2">重放会重建实时估计、运行时状态、最终状态实例和事件后快照链。</div></div>
            {lastMessage ? <div className="rounded-2xl border bg-emerald-50 p-3 text-emerald-900">{lastMessage}</div> : null}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
