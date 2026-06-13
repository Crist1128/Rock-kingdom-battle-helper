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
import { AvatarImage } from "@/components/ui/avatar";
import { ElfSearchSelect } from "@/components/EntitySearchSelect";
import { compactId, elementTypeNames, parseElementTypes, phaseName } from "@/lib/utils";
import type { LineupElfInput, PlayerElfBuildOut, TeamPresetOut } from "@/types/api";

interface SelfSlot { build_id: string; elf_id: string; active: boolean }
interface EnemySlot {
  elf_id: string;
  active: boolean;
  elf_name?: string | null;
  avatar?: string | null;
  element_types_json?: string | null;
}

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
  const selfTeamPresets = useQuery({
    queryKey: ["team-presets", "preparation", "self"],
    queryFn: () => api.teamPresets.list({ side_usage: "self" }),
  });
  const enemyTeamPresets = useQuery({
    queryKey: ["team-presets", "preparation", "enemy"],
    queryFn: () => api.teamPresets.list({ side_usage: "enemy" }),
  });

  const submitAndStartBattle = useMutation({
    mutationFn: async () => {
      if (!battleId) throw new Error("缺少 battle_id");
      const elves: LineupElfInput[] = [
        ...selfSlots.filter((item) => item.build_id && item.elf_id).map((item) => ({ side: "self" as const, elf_id: item.elf_id, build_id: item.build_id, is_active_elf: item.active })),
        ...enemySlots.filter((item) => item.elf_id).map((item) => ({ side: "enemy" as const, elf_id: item.elf_id, is_active_elf: item.active })),
      ];
      await api.battles.setupLineup(battleId, { elves });
      return api.battles.start(battleId, {
        self_active_elf_id: selfSlots.find((item) => item.active)?.elf_id,
        enemy_active_elf_id: enemySlots.find((item) => item.active)?.elf_id,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["battle", battleId] });
      queryClient.invalidateQueries({ queryKey: ["battle-state", battleId] });
      queryClient.invalidateQueries({ queryKey: ["enemy-estimate"] });
      navigate("/battle");
    },
  });

  const canSubmit = useMemo(() => Boolean(battleId && selfSlots.some((item) => item.build_id && item.active) && enemySlots.some((item) => item.elf_id && item.active)), [battleId, selfSlots, enemySlots]);

  const applySelfTeamPreset = (preset: TeamPresetOut) => {
    const next = Array.from({ length: 6 }, (_, index) => {
      const slot = preset.slots.find((item) => item.slot_index === index);
      return {
        build_id: slot?.build_id ?? "",
        elf_id: slot?.elf_id ?? "",
        active: index === 0 && Boolean(slot?.build_id),
      };
    });
    if (!next.some((slot) => slot.active)) {
      const firstFilledIndex = next.findIndex((slot) => slot.build_id && slot.elf_id);
      if (firstFilledIndex >= 0) next[firstFilledIndex].active = true;
    }
    setSelfSlots(next);
  };

  const applyEnemyTeamPreset = (preset: TeamPresetOut) => {
    const next = Array.from({ length: 6 }, (_, index) => {
      const slot = preset.slots.find((item) => item.slot_index === index);
      return {
        elf_id: slot?.elf_id ?? "",
        elf_name: slot?.elf_name ?? null,
        avatar: slot?.avatar ?? null,
        element_types_json: slot?.element_types_json ?? null,
        active: index === 0 && Boolean(slot?.elf_id),
      };
    });
    if (!next.some((slot) => slot.active)) {
      const firstFilledIndex = next.findIndex((slot) => slot.elf_id);
      if (firstFilledIndex >= 0) next[firstFilledIndex].active = true;
    }
    setEnemySlots(next);
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold">准备阶段</h1>
          <p className="mt-1 text-muted-foreground">录入我方配置和敌方精灵种类，初始化敌方面板估计，然后进入战斗。</p>
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

      <Card>
        <CardHeader>
          <CardTitle>配队快速填充</CardTitle>
          <CardDescription>选择已保存的己方配队或敌方热门阵容，自动填入下面 6 个槽位。</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2">
          <div>
            <label className="text-sm font-medium">己方配队</label>
            <Select
              value=""
              onChange={(event) => {
                const preset = selfTeamPresets.data?.find((item) => item.preset_id === event.target.value);
                if (preset) applySelfTeamPreset(preset);
              }}
            >
              <option value="">选择后填充己方阵容</option>
              {selfTeamPresets.data?.map((preset) => (
                <option key={preset.preset_id} value={preset.preset_id}>
                  {preset.preset_name} · {preset.slots.length} 只
                </option>
              ))}
            </Select>
          </div>
          <div>
            <label className="text-sm font-medium">敌方热门阵容</label>
            <Select
              value=""
              onChange={(event) => {
                const preset = enemyTeamPresets.data?.find((item) => item.preset_id === event.target.value);
                if (preset) applyEnemyTeamPreset(preset);
              }}
            >
              <option value="">选择后填充敌方阵容</option>
              {enemyTeamPresets.data?.map((preset) => (
                <option key={preset.preset_id} value={preset.preset_id}>
                  {preset.preset_name} · {preset.slots.length} 只
                </option>
              ))}
            </Select>
          </div>
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
                <PreparationSelfSelection build={builds.data?.find((item) => item.build_id === slot.build_id)} />
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
                <PreparationEnemySelection slot={slot} />
                <ElfSearchSelect label="敌方精灵" value={slot.elf_id} resultsMode="focus" onChange={(id, elf) => {
                  const next = [...enemySlots];
                  next[index] = {
                    ...next[index],
                    elf_id: id,
                    elf_name: elf.elf_name,
                    avatar: elf.avatar,
                    element_types_json: elf.element_types_json,
                  };
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
            阵容提交后，后端会初始化敌方面板估计档案。战斗开始后后端不允许直接重录阵容，应走后续纠错流程。
          </div>
          <Button
            disabled={!canSubmit || submitAndStartBattle.isPending}
            onClick={() => submitAndStartBattle.mutate()}
          >
            {submitAndStartBattle.isPending ? "提交并进入中..." : "提交阵容并进入战斗"}
          </Button>
        </CardContent>
      </Card>
      {submitAndStartBattle.error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          提交失败：{String(submitAndStartBattle.error.message ?? "unknown error")}
        </div>
      ) : null}
    </div>
  );
}

function PreparationSelfSelection({ build }: { build?: PlayerElfBuildOut }) {
  if (!build) {
    return <div className="mt-2 rounded-xl border border-dashed bg-slate-50 p-2 text-xs text-muted-foreground">未选择配置</div>;
  }
  const name = build.elf_name ?? compactId(build.elf_id);
  const elements = parseElementTypes(build.element_types_json);
  return (
    <div className="mt-2 flex items-center gap-3 rounded-xl border bg-slate-50 p-2">
      <AvatarImage src={build.avatar} alt={name} fallback={name} className="h-12 w-12" />
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-semibold">{name}</div>
        <div className="truncate text-xs text-muted-foreground">
          {build.build_name ? `${build.build_name} · ` : ""}
          {elements.length > 0 ? elementTypeNames(elements) : "未知系别"}
        </div>
      </div>
    </div>
  );
}

function PreparationEnemySelection({ slot }: { slot: EnemySlot }) {
  if (!slot.elf_id) {
    return <div className="mb-2 rounded-xl border border-dashed bg-slate-50 p-2 text-xs text-muted-foreground">未选择敌方精灵</div>;
  }
  const name = slot.elf_name ?? compactId(slot.elf_id);
  const elements = parseElementTypes(slot.element_types_json);
  return (
    <div className="mb-2 flex items-center gap-3 rounded-xl border bg-slate-50 p-2">
      <AvatarImage src={slot.avatar} alt={name} fallback={name} className="h-12 w-12" />
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-semibold">{name}</div>
        <div className="truncate text-xs text-muted-foreground">
          {elements.length > 0 ? elementTypeNames(elements) : compactId(slot.elf_id)}
        </div>
      </div>
    </div>
  );
}
