import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { useAppStore } from "@/store/useAppStore";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { ElfSearchSelect } from "@/components/EntitySearchSelect";
import { compactId, elementTypeNames, parseElementTypes, phaseName } from "@/lib/utils";
import type { LineupElfInput } from "@/types/api";

interface SelfSlot { build_id: string; elf_id: string; active: boolean }
interface EnemySlot { elf_id: string; active: boolean }

export function PreparationPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { currentBattleId, setCurrentBattleId } = useAppStore();
  const [battleIdInput, setBattleIdInput] = useState(currentBattleId ?? "");
  const [selfSlots, setSelfSlots] = useState<SelfSlot[]>(Array.from({ length: 6 }, () => ({ build_id: "", elf_id: "", active: false })));
  const [enemySlots, setEnemySlots] = useState<EnemySlot[]>(Array.from({ length: 6 }, () => ({ elf_id: "", active: false })));

  const battleId = currentBattleId;
  const battle = useQuery({ queryKey: ["battle", battleId], queryFn: () => api.battles.get(battleId!), enabled: Boolean(battleId) });
  const builds = useQuery({ queryKey: ["player-builds"], queryFn: () => api.playerBuilds.list() });

  const setupLineup = useMutation({
    mutationFn: () => {
      if (!battleId) throw new Error("缺少 battle_id");
      const elves: LineupElfInput[] = [
        ...selfSlots.filter((item) => item.build_id && item.elf_id).map((item) => ({ side: "self" as const, elf_id: item.elf_id, build_id: item.build_id, is_active_elf: item.active })),
        ...enemySlots.filter((item) => item.elf_id).map((item) => ({ side: "enemy" as const, elf_id: item.elf_id, is_active_elf: item.active })),
      ];
      return api.battles.setupLineup(battleId, { elves });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["battle", battleId] }),
  });

  const startBattle = useMutation({
    mutationFn: () => {
      if (!battleId) throw new Error("缺少 battle_id");
      return api.battles.start(battleId, {
        self_active_elf_id: selfSlots.find((item) => item.active)?.elf_id,
        enemy_active_elf_id: enemySlots.find((item) => item.active)?.elf_id,
      });
    },
    onSuccess: () => navigate("/battle"),
  });

  const canSubmit = useMemo(() => Boolean(battleId && selfSlots.some((item) => item.build_id && item.active) && enemySlots.some((item) => item.elf_id && item.active)), [battleId, selfSlots, enemySlots]);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold">准备阶段</h1>
          <p className="mt-1 text-muted-foreground">录入我方配置和敌方精灵种类，生成敌方候选配置，然后进入战斗。</p>
        </div>
        <Badge variant={battle.data?.phase === "preparation" ? "warning" : "outline"}>{phaseName(battle.data?.phase)}</Badge>
      </div>

      <Card>
        <CardContent className="flex items-end gap-3 pt-5">
          <div className="flex-1">
            <label className="text-sm font-medium">当前 battle_id</label>
            <Input value={battleIdInput} onChange={(e) => setBattleIdInput(e.target.value)} placeholder="从首页创建，或手动输入 battle_id" />
          </div>
          <Button onClick={() => setCurrentBattleId(battleIdInput.trim())} disabled={!battleIdInput.trim()}>使用此战斗</Button>
        </CardContent>
      </Card>

      <div className="grid grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>我方阵容</CardTitle>
            <CardDescription>必须选择己方完整配置，后端会复制面板属性和技能槽。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {selfSlots.map((slot, index) => (
              <div key={index} className="rounded-2xl border bg-white p-3">
                <div className="mb-2 flex items-center justify-between"><span className="font-medium">槽位 {index + 1}</span>{slot.active ? <Badge>首发</Badge> : null}</div>
                <Select value={slot.build_id} onChange={(e) => {
                  const build = builds.data?.find((item) => item.build_id === e.target.value);
                  const next = [...selfSlots];
                  next[index] = { ...next[index], build_id: e.target.value, elf_id: build?.elf_id ?? "" };
                  setSelfSlots(next);
                }}>
                  <option value="">选择己方配置</option>
                  {builds.data?.map((build) => {
                    const elfName = build.elf_name ?? compactId(build.elf_id);
                    const elements = parseElementTypes(build.element_types_json);
                    const elementText = elements.length > 0 ? ` · ${elementTypeNames(elements)}` : "";
                    const label = build.build_name ? `${build.build_name} · ${elfName}${elementText}` : `${elfName}${elementText}`;
                    return <option key={build.build_id} value={build.build_id}>{label}</option>;
                  })}
                </Select>
                <Button className="mt-2 w-full" variant="outline" size="sm" onClick={() => setSelfSlots(selfSlots.map((item, i) => ({ ...item, active: i === index })))}>设为首发</Button>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>敌方阵容</CardTitle>
            <CardDescription>敌方只确认精灵种类，不输入性格、个体资质和技能组。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {enemySlots.map((slot, index) => (
              <div key={index} className="rounded-2xl border bg-white p-3">
                <div className="mb-2 flex items-center justify-between"><span className="font-medium">槽位 {index + 1}</span>{slot.active ? <Badge>首发</Badge> : null}</div>
                <ElfSearchSelect label="敌方精灵" value={slot.elf_id} onChange={(id) => {
                  const next = [...enemySlots];
                  next[index] = { ...next[index], elf_id: id };
                  setEnemySlots(next);
                }} />
                <Button className="mt-2 w-full" variant="outline" size="sm" onClick={() => setEnemySlots(enemySlots.map((item, i) => ({ ...item, active: i === index })))}>设为首发</Button>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardContent className="flex items-center justify-between pt-5">
          <div className="text-sm text-muted-foreground">
            阵容提交后，后端会自动生成敌方候选。战斗开始后后端不允许直接重录阵容，应走后续纠错流程。
          </div>
          <div className="flex gap-2">
            <Button variant="outline" disabled={!canSubmit || setupLineup.isPending} onClick={() => setupLineup.mutate()}>{setupLineup.isPending ? "提交中..." : "提交阵容并生成候选"}</Button>
            <Button disabled={!canSubmit || startBattle.isPending} onClick={() => startBattle.mutate()}>{startBattle.isPending ? "进入中..." : "进入战斗"}</Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
