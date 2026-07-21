import { useEffect, useRef, useState } from "react";
import type { MouseEvent } from "react";
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
import { useToast } from "@/components/ui/toast";
import type {
  EnemyAvatarMatchedElfOut,
  EnemyLineupRecognitionOut,
  LineupElfInput,
  PlayerElfBuildOut,
  TeamPresetOut,
} from "@/types/api";

interface SelfSlot { build_id: string; elf_id: string; active: boolean }
interface EnemySlot {
  elf_id: string;
  active: boolean;
  elf_name?: string | null;
  avatar?: string | null;
  element_types_json?: string | null;
}

interface PreparationValidationResult {
  issues: string[];
  elves: LineupElfInput[];
  selfActiveElfId?: string;
  enemyActiveElfId?: string;
}

interface ScreenCapturePreview {
  file: File;
  url: string;
  width: number;
  height: number;
}

interface CropSelection {
  x: number;
  y: number;
  width: number;
  height: number;
}

const wait = (ms: number) => new Promise<void>((resolve) => window.setTimeout(resolve, ms));

const isSelfSlotComplete = (slot: SelfSlot) => Boolean(slot.build_id && slot.elf_id);
const isEnemySlotComplete = (slot: EnemySlot) => Boolean(slot.elf_id);

function duplicateValues(values: string[]): string[] {
  const seen = new Set<string>();
  const duplicates = new Set<string>();
  values.forEach((value) => {
    if (!value) return;
    if (seen.has(value)) duplicates.add(value);
    seen.add(value);
  });
  return [...duplicates];
}

function preparationRequiredMessage(issues: string[]) {
  return `提交前请先完成：\n${issues.map((item) => `- ${item}`).join("\n")}`;
}

async function canvasToPngFile(canvas: HTMLCanvasElement, fileName: string): Promise<File> {
  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
  if (!blob) throw new Error("截图生成失败：浏览器未能导出 PNG");
  return new File([blob], fileName, { type: "image/png" });
}

async function loadImage(url: string): Promise<HTMLImageElement> {
  const image = new Image();
  image.src = url;
  await image.decode();
  return image;
}

export function PreparationPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const { currentBattleId, setCurrentBattleId } = useAppStore();
  const [battleIdInput, setBattleIdInput] = useState(currentBattleId ?? "");
  const [selfSlots, setSelfSlots] = useState<SelfSlot[]>(Array.from({ length: 6 }, () => ({ build_id: "", elf_id: "", active: false })));
  const [enemySlots, setEnemySlots] = useState<EnemySlot[]>(Array.from({ length: 6 }, () => ({ elf_id: "", active: false })));
  const [recognitionFile, setRecognitionFile] = useState<File | null>(null);
  const [recognitionResult, setRecognitionResult] = useState<EnemyLineupRecognitionOut | null>(null);
  const [hidePageBeforeCapture, setHidePageBeforeCapture] = useState(false);
  const [screenCapture, setScreenCapture] = useState<ScreenCapturePreview | null>(null);
  const [cropSelection, setCropSelection] = useState<CropSelection | null>(null);
  const [cropDragStart, setCropDragStart] = useState<{ x: number; y: number } | null>(null);
  const [captureError, setCaptureError] = useState<string | null>(null);
  const [preparationIssues, setPreparationIssues] = useState<string[]>([]);
  const capturePreviewRef = useRef<HTMLImageElement | null>(null);

  useEffect(() => {
    return () => {
      if (screenCapture) URL.revokeObjectURL(screenCapture.url);
    };
  }, [screenCapture]);

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

  const recognizeEnemyLineup = useMutation({
    mutationFn: (file: File) => api.recognition.enemyLineup(file, 5),
    onSuccess: (result) => setRecognitionResult(result),
  });

  const validatePreparation = (): PreparationValidationResult => {
    const issues: string[] = [];
    const completeSelfSlots = selfSlots
      .map((slot, index) => ({ slot, index }))
      .filter(({ slot }) => isSelfSlotComplete(slot));
    const completeEnemySlots = enemySlots
      .map((slot, index) => ({ slot, index }))
      .filter(({ slot }) => isEnemySlotComplete(slot));
    const selfActiveSlots = selfSlots.map((slot, index) => ({ slot, index })).filter(({ slot }) => slot.active);
    const enemyActiveSlots = enemySlots.map((slot, index) => ({ slot, index })).filter(({ slot }) => slot.active);
    const validSelfActiveSlots = completeSelfSlots.filter(({ slot }) => slot.active);
    const validEnemyActiveSlots = completeEnemySlots.filter(({ slot }) => slot.active);

    if (!battleId) {
      issues.push("请先从首页创建战斗，或输入 battle_id 后点击“使用此战斗”。");
    }
    if (battle.isLoading) {
      issues.push("当前战斗信息仍在读取，请稍后再提交。");
    }
    if (battle.error) {
      issues.push(`当前战斗读取失败：${battle.error.message}`);
    }
    if (battle.data?.phase && battle.data.phase !== "preparation") {
      issues.push(`当前战斗阶段是“${phaseName(battle.data.phase)}”，只有准备阶段可以直接录入阵容。`);
    }

    if (completeSelfSlots.length === 0) {
      issues.push("己方阵容至少需要选择 1 个完整配置。");
    }
    if (completeEnemySlots.length === 0) {
      issues.push("敌方阵容至少需要选择 1 只精灵。");
    }
    if (completeSelfSlots.length > 6 || completeEnemySlots.length > 6) {
      issues.push("每个阵营最多只能录入 6 只精灵。");
    }

    const incompleteSelfActiveSlots = selfActiveSlots.filter(({ slot }) => !isSelfSlotComplete(slot));
    if (incompleteSelfActiveSlots.length > 0) {
      issues.push(
        `己方槽位 ${incompleteSelfActiveSlots.map(({ index }) => index + 1).join("、")} 被设为首发，但还没有选择完整配置。`,
      );
    }
    const incompleteEnemyActiveSlots = enemyActiveSlots.filter(({ slot }) => !isEnemySlotComplete(slot));
    if (incompleteEnemyActiveSlots.length > 0) {
      issues.push(
        `敌方槽位 ${incompleteEnemyActiveSlots.map(({ index }) => index + 1).join("、")} 被设为首发，但还没有选择精灵。`,
      );
    }
    if (validSelfActiveSlots.length === 0) {
      issues.push("请把 1 个已选择配置的己方槽位设为首发。");
    } else if (validSelfActiveSlots.length > 1) {
      issues.push("己方只能有 1 个首发槽位。");
    }
    if (validEnemyActiveSlots.length === 0) {
      issues.push("请把 1 个已选择精灵的敌方槽位设为首发。");
    } else if (validEnemyActiveSlots.length > 1) {
      issues.push("敌方只能有 1 个首发槽位。");
    }

    const duplicateSelfElfIds = duplicateValues(completeSelfSlots.map(({ slot }) => slot.elf_id));
    if (duplicateSelfElfIds.length > 0) {
      issues.push(`己方阵容中有重复精灵：${duplicateSelfElfIds.join("、")}。`);
    }
    const duplicateEnemyElfIds = duplicateValues(completeEnemySlots.map(({ slot }) => slot.elf_id));
    if (duplicateEnemyElfIds.length > 0) {
      issues.push(`敌方阵容中有重复精灵：${duplicateEnemyElfIds.join("、")}。`);
    }

    const elves: LineupElfInput[] = [
      ...completeSelfSlots.map(({ slot }) => ({
        side: "self" as const,
        elf_id: slot.elf_id,
        build_id: slot.build_id,
        is_active_elf: slot.active,
      })),
      ...completeEnemySlots.map(({ slot }) => ({
        side: "enemy" as const,
        elf_id: slot.elf_id,
        is_active_elf: slot.active,
      })),
    ];

    return {
      issues,
      elves,
      selfActiveElfId: validSelfActiveSlots[0]?.slot.elf_id,
      enemyActiveElfId: validEnemyActiveSlots[0]?.slot.elf_id,
    };
  };

  const submitAndStartBattle = useMutation({
    mutationFn: async () => {
      if (!battleId) throw new Error("缺少 battle_id");
      const preparation = validatePreparation();
      if (preparation.issues.length > 0) {
        throw new Error(`准备阶段必做项未完成：${preparation.issues.join("；")}`);
      }
      await api.battles.setupLineup(battleId, { elves: preparation.elves });
      return api.battles.start(battleId, {
        self_active_elf_id: preparation.selfActiveElfId,
        enemy_active_elf_id: preparation.enemyActiveElfId,
      });
    },
    onSuccess: () => {
      setPreparationIssues([]);
      queryClient.invalidateQueries({ queryKey: ["battle", battleId] });
      queryClient.invalidateQueries({ queryKey: ["battle-state", battleId] });
      queryClient.invalidateQueries({ queryKey: ["enemy-estimate"] });
      navigate("/battle");
    },
  });

  const handleSubmitAndStart = () => {
    const preparation = validatePreparation();
    if (preparation.issues.length > 0) {
      submitAndStartBattle.reset();
      setPreparationIssues(preparation.issues);
      toast(preparationRequiredMessage(preparation.issues), "error");
      return;
    }
    submitAndStartBattle.reset();
    setPreparationIssues([]);
    submitAndStartBattle.mutate();
  };

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

  const applyRecognizedEnemy = (slotIndex: number, elf: EnemyAvatarMatchedElfOut) => {
    setEnemySlots((current) =>
      current.map((slot, index) =>
        index === slotIndex
          ? {
              ...slot,
              elf_id: elf.elf_id,
              elf_name: elf.elf_name,
              avatar: elf.avatar,
              element_types_json: elf.element_types_json,
              active: slot.active || !current.some((item) => item.active),
            }
          : slot,
      ),
    );
  };

  const applyTopRecognitionCandidates = () => {
    if (!recognitionResult) return;
    const next = [...enemySlots];
    recognitionResult.slots.forEach((slot) => {
      const matched = slot.candidates[0]?.matched_elves[0];
      const index = slot.slot_index - 1;
      if (!matched || index < 0 || index >= next.length) return;
      next[index] = {
        ...next[index],
        elf_id: matched.elf_id,
        elf_name: matched.elf_name,
        avatar: matched.avatar,
        element_types_json: matched.element_types_json,
      };
    });
    if (!next.some((slot) => slot.active)) {
      const firstFilledIndex = next.findIndex((slot) => slot.elf_id);
      if (firstFilledIndex >= 0) next[firstFilledIndex].active = true;
    }
    setEnemySlots(next);
  };

  const captureScreenFrame = async () => {
    setCaptureError(null);
    setRecognitionResult(null);
    if (!navigator.mediaDevices?.getDisplayMedia) {
      setCaptureError("当前浏览器不支持屏幕捕获，请改用上传截图。");
      return;
    }

    let stream: MediaStream | null = null;
    const oldOpacity = document.documentElement.style.opacity;
    try {
      stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
      const video = document.createElement("video");
      video.srcObject = stream;
      video.muted = true;
      video.playsInline = true;
      await video.play();

      if (hidePageBeforeCapture) {
        document.documentElement.style.opacity = "0";
        await wait(600);
      }

      const width = video.videoWidth;
      const height = video.videoHeight;
      if (!width || !height) throw new Error("截图失败：未获取到有效画面尺寸");

      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      const context = canvas.getContext("2d");
      if (!context) throw new Error("截图失败：浏览器未能创建画布");
      context.drawImage(video, 0, 0, width, height);

      const file = await canvasToPngFile(canvas, "screen-capture.png");
      const url = URL.createObjectURL(file);
      setScreenCapture({ file, url, width, height });
      setCropSelection(null);
      setRecognitionFile(file);
    } catch (error) {
      setCaptureError(error instanceof Error ? error.message : "屏幕捕获已取消或失败");
    } finally {
      document.documentElement.style.opacity = oldOpacity;
      stream?.getTracks().forEach((track) => track.stop());
    }
  };

  const getCapturePoint = (event: MouseEvent<HTMLDivElement>) => {
    const image = capturePreviewRef.current;
    if (!image || !screenCapture) return null;
    const rect = image.getBoundingClientRect();
    const rawX = ((event.clientX - rect.left) / rect.width) * screenCapture.width;
    const rawY = ((event.clientY - rect.top) / rect.height) * screenCapture.height;
    return {
      x: Math.max(0, Math.min(screenCapture.width, rawX)),
      y: Math.max(0, Math.min(screenCapture.height, rawY)),
    };
  };

  const startCropDrag = (event: MouseEvent<HTMLDivElement>) => {
    const point = getCapturePoint(event);
    if (!point) return;
    setCropDragStart(point);
    setCropSelection({ x: point.x, y: point.y, width: 0, height: 0 });
  };

  const updateCropDrag = (event: MouseEvent<HTMLDivElement>) => {
    if (!cropDragStart) return;
    const point = getCapturePoint(event);
    if (!point) return;
    setCropSelection({
      x: Math.min(cropDragStart.x, point.x),
      y: Math.min(cropDragStart.y, point.y),
      width: Math.abs(point.x - cropDragStart.x),
      height: Math.abs(point.y - cropDragStart.y),
    });
  };

  const recognizeCapturedImage = async (useSelection: boolean) => {
    if (!screenCapture) return;
    setCaptureError(null);
    try {
      let file = screenCapture.file;
      const shouldCrop =
        useSelection && cropSelection && cropSelection.width >= 16 && cropSelection.height >= 16;

      if (shouldCrop) {
        const image = await loadImage(screenCapture.url);
        const canvas = document.createElement("canvas");
        canvas.width = Math.round(cropSelection.width);
        canvas.height = Math.round(cropSelection.height);
        const context = canvas.getContext("2d");
        if (!context) throw new Error("裁剪失败：浏览器未能创建画布");
        context.drawImage(
          image,
          cropSelection.x,
          cropSelection.y,
          cropSelection.width,
          cropSelection.height,
          0,
          0,
          canvas.width,
          canvas.height,
        );
        file = await canvasToPngFile(canvas, "game-window-crop.png");
      }

      setRecognitionFile(file);
      recognizeEnemyLineup.mutate(file);
    } catch (error) {
      setCaptureError(error instanceof Error ? error.message : "裁剪截图失败");
    }
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
              <div key={index} className="rounded-2xl border bg-raised/60 p-3">
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
            <div className="rounded-2xl border border-dashed bg-raised/60 p-3">
              <div className="mb-2">
                <div className="text-sm font-semibold">截图识别敌方阵容（候选确认）</div>
                <div className="text-xs text-muted-foreground">
                  可上传图片，也可调用浏览器截屏。识别只生成每个槽位的 Top 候选；需要手动点击候选才会写入下方阵容。
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Input
                  className="max-w-xs"
                  type="file"
                  accept="image/*"
                  onChange={(event) => {
                    setRecognitionFile(event.target.files?.[0] ?? null);
                    setRecognitionResult(null);
                    setCaptureError(null);
                  }}
                />
                <Button
                  variant="outline"
                  disabled={!recognitionFile || recognizeEnemyLineup.isPending}
                  onClick={() => recognitionFile && recognizeEnemyLineup.mutate(recognitionFile)}
                >
                  {recognizeEnemyLineup.isPending ? "识别中..." : "识别敌方阵容"}
                </Button>
                <Button
                  variant="secondary"
                  disabled={!recognitionResult}
                  onClick={applyTopRecognitionCandidates}
                >
                  采用每槽首个可映射候选
                </Button>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <Button
                  variant="outline"
                  disabled={recognizeEnemyLineup.isPending}
                  onClick={captureScreenFrame}
                >
                  截屏/选择游戏窗口
                </Button>
                <label className="flex items-center gap-1 text-xs text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={hidePageBeforeCapture}
                    onChange={(event) => setHidePageBeforeCapture(event.target.checked)}
                  />
                  捕获前临时隐藏本页面 0.6 秒
                </label>
                <span className="text-[11px] text-muted-foreground">
                  浏览器会弹出授权框；建议选择游戏窗口，若选择整个屏幕可在下方框选游戏区域。
                </span>
              </div>
              {captureError ? (
                <div className="mt-2 rounded-xl border border-warning/25 bg-warning/10 p-2 text-xs text-warning">
                  截屏提示：{captureError}
                </div>
              ) : null}
              {screenCapture ? (
                <div className="mt-3 rounded-xl border bg-raised/60 p-2">
                  <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                    <div className="text-xs text-muted-foreground">
                      已捕获 {screenCapture.width}×{screenCapture.height}。按住鼠标在预览图上拖拽框选游戏界面。
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={recognizeEnemyLineup.isPending}
                        onClick={() => recognizeCapturedImage(false)}
                      >
                        识别整张截图
                      </Button>
                      <Button
                        size="sm"
                        disabled={
                          !cropSelection ||
                          cropSelection.width < 16 ||
                          cropSelection.height < 16 ||
                          recognizeEnemyLineup.isPending
                        }
                        onClick={() => recognizeCapturedImage(true)}
                      >
                        识别框选区域
                      </Button>
                    </div>
                  </div>
                  <div className="max-h-[360px] overflow-auto rounded-lg border bg-black">
                    <div
                      className="relative inline-block cursor-crosshair"
                      onMouseDown={startCropDrag}
                      onMouseMove={updateCropDrag}
                      onMouseUp={() => setCropDragStart(null)}
                      onMouseLeave={() => setCropDragStart(null)}
                    >
                      <img
                        ref={capturePreviewRef}
                        src={screenCapture.url}
                        alt="屏幕捕获预览"
                        draggable={false}
                        className="block max-h-[360px] max-w-full select-none object-contain"
                      />
                      {cropSelection && cropSelection.width > 0 && cropSelection.height > 0 ? (
                        <div
                          className="pointer-events-none absolute border-2 border-info bg-info/20"
                          style={{
                            left: `${(cropSelection.x / screenCapture.width) * 100}%`,
                            top: `${(cropSelection.y / screenCapture.height) * 100}%`,
                            width: `${(cropSelection.width / screenCapture.width) * 100}%`,
                            height: `${(cropSelection.height / screenCapture.height) * 100}%`,
                          }}
                        />
                      ) : null}
                    </div>
                  </div>
                </div>
              ) : null}
              {recognizeEnemyLineup.error ? (
                <div className="mt-2 rounded-xl border border-destructive/25 bg-destructive/10 p-2 text-xs text-destructive">
                  识别失败：{recognizeEnemyLineup.error.message}
                </div>
              ) : null}
              {recognitionResult ? (
                <div className="mt-3 space-y-2">
                  <div className="text-xs text-muted-foreground">
                    截图尺寸 {recognitionResult.source_image_size[0]}×{recognitionResult.source_image_size[1]}，
                    模板 {recognitionResult.icon_template_count} 个。请逐槽确认，Top1 不一定总是正确。
                  </div>
                  {recognitionResult.warnings.map((warning) => (
                    <div key={warning} className="rounded-lg bg-warning/10 px-2 py-1 text-xs text-warning">
                      {warning}
                    </div>
                  ))}
                  {recognitionResult.debug_artifacts ? (
                    <div className="rounded-xl border bg-raised/60 p-2">
                      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                        <div>
                          <div className="text-xs font-semibold">识别调试图</div>
                          <div className="text-[11px] text-muted-foreground">
                            运行 ID {recognitionResult.debug_artifacts.run_id.slice(0, 8)}；约 {Math.round(recognitionResult.debug_artifacts.expires_after_seconds / 3600)} 小时后由后续请求清理。
                          </div>
                        </div>
                        <div className="flex flex-wrap gap-2 text-[11px]">
                          <a className="text-info underline" href={recognitionResult.debug_artifacts.annotated_image_url} target="_blank" rel="noreferrer">打开框选图</a>
                          <a className="text-info underline" href={recognitionResult.debug_artifacts.contact_sheet_url} target="_blank" rel="noreferrer">打开总览图</a>
                        </div>
                      </div>
                      <div className="grid gap-2 md:grid-cols-2">
                        <a href={recognitionResult.debug_artifacts.annotated_image_url} target="_blank" rel="noreferrer" className="block rounded-lg border bg-raised/60 p-2">
                          <div className="mb-1 text-[11px] font-medium">整图框选</div>
                          <img src={recognitionResult.debug_artifacts.annotated_image_url} alt="识别框选图" className="max-h-56 w-full rounded object-contain" />
                        </a>
                        <a href={recognitionResult.debug_artifacts.contact_sheet_url} target="_blank" rel="noreferrer" className="block rounded-lg border bg-raised/60 p-2">
                          <div className="mb-1 text-[11px] font-medium">Top2 总览</div>
                          <img src={recognitionResult.debug_artifacts.contact_sheet_url} alt="识别候选总览图" className="max-h-56 w-full rounded object-contain" />
                        </a>
                      </div>
                      <div className="mt-2 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                        {recognitionResult.debug_artifacts.slots.map((debugSlot) => (
                          <div key={debugSlot.slot_index} className="rounded-lg border bg-raised/60 p-2">
                            <div className="mb-1 flex items-center justify-between text-[11px] font-medium">
                              <span>槽位 {debugSlot.slot_index} 抄像检查</span>
                              <span className="flex gap-2 font-normal">
                                <a className="text-info underline" href={debugSlot.crop_url} target="_blank" rel="noreferrer">裁剪</a>
                                <a className="text-info underline" href={debugSlot.detail_url} target="_blank" rel="noreferrer">详情</a>
                                <a className="text-info underline" href={debugSlot.top5_url} target="_blank" rel="noreferrer">Top2</a>
                              </span>
                            </div>
                            <a href={debugSlot.detail_url} target="_blank" rel="noreferrer">
                              <img src={debugSlot.detail_url} alt={`槽位 ${debugSlot.slot_index} 头像识别详情`} className="max-h-48 w-full rounded object-contain" />
                            </a>
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : null}
                  <div className="grid gap-2">
                    {recognitionResult.slots.map((slot) => (
                      <div key={slot.slot_index} className="rounded-xl border bg-raised/60 p-2">
                        <div className="mb-2 flex items-center justify-between">
                          <span className="text-xs font-semibold">槽位 {slot.slot_index}</span>
                          <span className="text-[11px] text-muted-foreground">
                            {slot.location_method} · 定位 {slot.location_confidence.toFixed(2)} · 框 ({slot.box.x1},{slot.box.y1})-({slot.box.x2},{slot.box.y2})
                          </span>
                        </div>
                        <div className="space-y-2">
                          {slot.candidates.map((candidate, candidateIndex) => (
                            <div key={`${slot.slot_index}-${candidate.file_name}`} className="rounded-lg border bg-raised/60 p-2">
                              <div className="flex items-center gap-2">
                                <AvatarImage
                                  src={candidate.icon_url}
                                  alt={candidate.elf_name}
                                  fallback={candidate.elf_name}
                                  className="h-10 w-10 rounded-full"
                                />
                                <div className="min-w-0 flex-1">
                                  <div className="truncate text-xs font-semibold">
                                    Top{candidateIndex + 1} {candidate.dex_no} {candidate.elf_name}
                                  </div>
                                  <div className="text-[11px] text-muted-foreground">
                                    综合 {candidate.score.toFixed(3)} · {candidate.confidence_level}
                                  </div>
                                </div>
                              </div>
                              <div className="mt-2 flex flex-wrap gap-1">
                                {candidate.matched_elves.length > 0 ? (
                                  candidate.matched_elves.map((elf) => (
                                    <Button
                                      key={elf.elf_id}
                                      size="sm"
                                      variant="outline"
                                      onClick={() => applyRecognizedEnemy(slot.slot_index - 1, elf)}
                                    >
                                      采用：{elf.elf_name}
                                    </Button>
                                  ))
                                ) : (
                                  <span className="text-[11px] text-warning">该候选暂未映射到数据库</span>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
            {enemySlots.map((slot, index) => (
              <div key={index} className="rounded-2xl border bg-raised/60 p-3">
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
        <CardContent className="space-y-3 pt-5">
          <div className="flex items-center justify-between gap-4">
            <div className="text-sm text-muted-foreground">
              阵容提交后，后端会初始化敌方面板估计档案。战斗开始后后端不允许直接重录阵容，应走后续纠错流程。
            </div>
            <Button
              disabled={submitAndStartBattle.isPending}
              onClick={handleSubmitAndStart}
            >
              {submitAndStartBattle.isPending ? "提交并进入中..." : "提交阵容并进入战斗"}
            </Button>
          </div>
          <div className="rounded-xl border border-warning/25 bg-warning/10 p-3 text-xs text-warning">
            准备阶段必做项：选择当前战斗；己方至少 1 个完整配置；敌方至少 1 只精灵；双方各设置 1 个有效首发。
            缺项时点击提交会弹窗列出具体问题。
          </div>
          {preparationIssues.length > 0 ? (
            <div className="rounded-xl border border-destructive/25 bg-destructive/10 p-3 text-sm text-destructive">
              <div className="font-semibold">提交前请先完成：</div>
              <ul className="mt-1 list-disc space-y-1 pl-5">
                {preparationIssues.map((issue) => (
                  <li key={issue}>{issue}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </CardContent>
      </Card>
      {submitAndStartBattle.error ? (
        <div className="rounded-xl border border-destructive/25 bg-destructive/10 p-3 text-sm text-destructive">
          提交失败：{String(submitAndStartBattle.error.message ?? "unknown error")}
        </div>
      ) : null}
    </div>
  );
}

function PreparationSelfSelection({ build }: { build?: PlayerElfBuildOut }) {
  if (!build) {
    return <div className="mt-2 rounded-xl border border-dashed bg-raised/60 p-2 text-xs text-muted-foreground">未选择配置</div>;
  }
  const name = build.elf_name ?? compactId(build.elf_id);
  const elements = parseElementTypes(build.element_types_json);
  return (
    <div className="mt-2 flex items-center gap-3 rounded-xl border bg-raised/60 p-2">
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
    return <div className="mb-2 rounded-xl border border-dashed bg-raised/60 p-2 text-xs text-muted-foreground">未选择敌方精灵</div>;
  }
  const name = slot.elf_name ?? compactId(slot.elf_id);
  const elements = parseElementTypes(slot.element_types_json);
  return (
    <div className="mb-2 flex items-center gap-3 rounded-xl border bg-raised/60 p-2">
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
