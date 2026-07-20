import type {
  BattleCreate,
  BattleEffectSnapshotOut,
  BattleEventCreate,
  BattleEventCorrectInput,
  BattleEventOut,
  BattleEventVoidInput,
  BattleOut,
  BattlePurgePlanOut,
  BattlePurgeResultOut,
  BattleReplayResult,
  BattleStateOut,
  BattleTimelineTurnOut,
  DamageEventCreate,
  DamageEventCreateResult,
  DamageCalculatorBootstrapOut,
  DamageCalculatorCalculateInput,
  DamageCalculatorInferAttackerInput,
  DamageCalculatorInferAttackerOut,
  DamageCalculatorInferDefenderInput,
  DamageCalculatorInferDefenderOut,
  DamageCalculatorResultOut,
  EffectApplyInput,
  EffectDefinitionOut,
  EnemyLineupRecognitionOut,
  EvolutionChainSyncRequest,
  EvolutionChainSyncResponse,
  EnemyDefaultConfigInput,
  EnemyPanelEstimateEvidenceOut,
  EnemyPanelEstimateOut,
  EndTurnInput,
  EndTurnResult,
  ElfDefinitionOut,
  ElfEvolutionChainOut,
  LineupInput,
  LineupOut,
  NatureDefinitionOut,
  ObservationCreate,
  ObservationProcessResult,
  PlayerElfBuildCreate,
  PlayerElfBuildOut,
  ProjectBootstrapLocalRequest,
  ProjectDataBootstrapStatus,
  ResourceChangeEventCreate,
  RocomCheckRequest,
  RocomCheckResponse,
  RocomDataUpdateAccepted,
  RocomDataUpdateJobStatus,
  RocomDataUpdateRequest,
  RocomLocalImportRequest,
  RuntimeFormChangeInput,
  SkillDefinitionOut,
  SkillSlotRuntimeUpdateInput,
  SkillRuleCapabilityAuditOut,
  SkillRuleManualUpdate,
  SkillRuleReviewOut,
  SkillUseEventCreate,
  StartBattleInput,
  StaticSkillRuleSyncRequest,
  StaticSkillRuleSyncResponse,
  SwitchElfInput,
  TeamPresetCreate,
  TeamPresetOut,
} from "@/types/api";

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(formatApiErrorMessage(status, detail));
    this.status = status;
    this.detail = detail;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function formatValidationDetail(detail: unknown): string {
  if (!isRecord(detail)) return String(detail);
  const msg = typeof detail.msg === "string" ? detail.msg : String(detail.type ?? "请求参数校验失败");
  const loc = Array.isArray(detail.loc) ? detail.loc.map(String).join(".") : "";
  return loc ? `${loc}: ${msg}` : msg;
}

function formatApiErrorMessage(status: number, detail: unknown): string {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) return detail.map(formatValidationDetail).join("；");
  if (isRecord(detail)) {
    const fastApiDetail = detail.detail;
    if (typeof fastApiDetail === "string" && fastApiDetail.trim()) return fastApiDetail;
    if (Array.isArray(fastApiDetail)) return fastApiDetail.map(formatValidationDetail).join("；");
    if (isRecord(fastApiDetail)) return JSON.stringify(fastApiDetail);
    if (typeof detail.message === "string" && detail.message.trim()) return detail.message;
  }
  return `API request failed: ${status}`;
}

async function readResponseErrorDetail(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return response.statusText;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    throw new ApiError(response.status, await readResponseErrorDetail(response));
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function uploadRequest<T>(path: string, formData: FormData): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    throw new ApiError(response.status, await readResponseErrorDetail(response));
  }

  return (await response.json()) as T;
}

const qs = (params: Record<string, string | number | boolean | null | undefined>) => {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  });
  const text = search.toString();
  return text ? `?${text}` : "";
};

export const api = {
  health: () => request<{ status: string }>("/health"),

  recognition: {
    enemyLineup: (file: File, topK = 2, includeDebug = true) => {
      const formData = new FormData();
      formData.append("file", file);
      return uploadRequest<EnemyLineupRecognitionOut>(
        `/recognition/enemy-lineup${qs({ top_k: topK, include_debug: includeDebug })}`,
        formData,
      );
    },
  },

  elves: {
    list: (params: { q?: string; limit?: number; offset?: number } = {}) =>
      request<ElfDefinitionOut[]>(`/elves${qs({ limit: 50, ...params })}`),
    get: (elfId: string) => request<ElfDefinitionOut>(`/elves/${elfId}`),
    evolutionChain: (elfId: string) =>
      request<ElfEvolutionChainOut>(`/elves/${elfId}/evolution-chain`),
    skills: (elfId: string, params: { q?: string; limit?: number; offset?: number } = {}) =>
      request<SkillDefinitionOut[]>(`/elves/${elfId}/skills${qs({ limit: 500, ...params })}`),
  },

  skills: {
    list: (params: { q?: string; limit?: number; offset?: number } = {}) =>
      request<SkillDefinitionOut[]>(`/skills${qs({ limit: 50, ...params })}`),
    review: (
      params: { q?: string; review_status?: string; limit?: number; offset?: number } = {},
    ) => request<SkillRuleReviewOut[]>(`/skills/review${qs({ limit: 50, ...params })}`),
    capabilityAudit: () => request<SkillRuleCapabilityAuditOut>("/skills/capability-audit"),
    get: (skillId: string) => request<SkillDefinitionOut>(`/skills/${skillId}`),
    updateRules: (skillId: string, payload: SkillRuleManualUpdate, adminToken?: string) =>
      request<SkillRuleReviewOut>(`/skills/${skillId}/rules`, {
        method: "PUT",
        headers: adminToken ? { "X-Admin-Token": adminToken } : undefined,
        body: JSON.stringify(payload),
      }),
  },

  natures: {
    list: (params: { q?: string; limit?: number; offset?: number } = {}) =>
      request<NatureDefinitionOut[]>(`/natures${qs({ limit: 100, ...params })}`),
    get: (natureId: string) => request<NatureDefinitionOut>(`/natures/${natureId}`),
  },

  damageCalculator: {
    bootstrap: () => request<DamageCalculatorBootstrapOut>("/damage-calculator/bootstrap"),
    calculate: (payload: DamageCalculatorCalculateInput) =>
      request<DamageCalculatorResultOut>("/damage-calculator/calculate", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    inferDefender: (payload: DamageCalculatorInferDefenderInput) =>
      request<DamageCalculatorInferDefenderOut>("/damage-calculator/infer-defender", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    inferAttacker: (payload: DamageCalculatorInferAttackerInput) =>
      request<DamageCalculatorInferAttackerOut>("/damage-calculator/infer-attacker", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
  },

  effects: {
    list: (params: { q?: string; category?: string; owner_scope?: string; limit?: number; offset?: number } = {}) =>
      request<EffectDefinitionOut[]>(`/effects${qs({ limit: 80, ...params })}`),
    get: (effectId: string) => request<EffectDefinitionOut>(`/effects/${effectId}`),
    apply: (payload: EffectApplyInput) =>
      request<Record<string, unknown>>("/effects/instances", { method: "POST", body: JSON.stringify(payload) }),
    remove: (instanceId: string, payload?: { turn_number?: number | null; reason?: string | null }) =>
      request<Record<string, unknown>>(`/effects/instances/${instanceId}`, {
        method: "DELETE",
        body: JSON.stringify(payload ?? { reason: "manual_remove" }),
      }),
  },

  playerBuilds: {
    list: (elfId?: string) => request<PlayerElfBuildOut[]>(`/player-builds${qs({ elf_id: elfId })}`),
    get: (buildId: string) => request<PlayerElfBuildOut>(`/player-builds/${buildId}`),
    create: (payload: PlayerElfBuildCreate) =>
      request<PlayerElfBuildOut>("/player-builds", { method: "POST", body: JSON.stringify(payload) }),
    update: (buildId: string, payload: PlayerElfBuildCreate) =>
      request<PlayerElfBuildOut>(`/player-builds/${buildId}`, { method: "PUT", body: JSON.stringify(payload) }),
    replaceSkills: (buildId: string, skillIds: string[]) =>
      request<PlayerElfBuildOut>(`/player-builds/${buildId}/skills`, {
        method: "PUT",
        body: JSON.stringify({ skill_ids: skillIds }),
      }),
    delete: (buildId: string) =>
      request<void>(`/player-builds/${buildId}`, { method: "DELETE" }),
  },

  teamPresets: {
    list: (params: { side_usage?: string; source_type?: string } = {}) =>
      request<TeamPresetOut[]>(`/team-presets${qs(params)}`),
    get: (presetId: string) => request<TeamPresetOut>(`/team-presets/${presetId}`),
    create: (payload: TeamPresetCreate) =>
      request<TeamPresetOut>("/team-presets", { method: "POST", body: JSON.stringify(payload) }),
    update: (presetId: string, payload: TeamPresetCreate) =>
      request<TeamPresetOut>(`/team-presets/${presetId}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      }),
    delete: (presetId: string) => request<void>(`/team-presets/${presetId}`, { method: "DELETE" }),
  },

  battles: {
    list: (params: { phase?: string; include_archived?: boolean; limit?: number; offset?: number } = {}) =>
      request<BattleOut[]>(`/battles${qs({ limit: 50, ...params })}`),
    create: (payload: BattleCreate) =>
      request<BattleOut>("/battles", { method: "POST", body: JSON.stringify(payload) }),
    get: (battleId: string) => request<BattleOut>(`/battles/${battleId}`),
    state: (battleId: string) => request<BattleStateOut>(`/battles/${battleId}/state`),
    setupLineup: (battleId: string, payload: LineupInput) =>
      request<LineupOut>(`/battles/${battleId}/lineup`, { method: "POST", body: JSON.stringify(payload) }),
    start: (battleId: string, payload: StartBattleInput) =>
      request<BattleOut>(`/battles/${battleId}/start`, { method: "POST", body: JSON.stringify(payload) }),
    switchElf: (battleId: string, payload: SwitchElfInput) =>
      request<BattleOut>(`/battles/${battleId}/switch`, { method: "POST", body: JSON.stringify(payload) }),
    changeRuntimeForm: (battleId: string, stateId: string, payload: RuntimeFormChangeInput) =>
      request<BattleStateOut>(`/battles/${battleId}/elves/${stateId}/runtime-form`, {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    updateSkillSlotRuntime: (
      battleId: string,
      slotId: string,
      payload: SkillSlotRuntimeUpdateInput,
    ) =>
      request<BattleStateOut>(`/battles/${battleId}/skill-slots/${slotId}/runtime`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      }),
    endTurn: (battleId: string, payload: EndTurnInput = {}) =>
      request<EndTurnResult>(`/battles/${battleId}/turns/end`, {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    finish: (battleId: string) =>
      request<BattleOut>(`/battles/${battleId}/finish`, { method: "POST" }),
    archive: (battleId: string) =>
      request<BattleOut>(`/battles/${battleId}/archive`, { method: "POST" }),
    createDamageEvent: (battleId: string, payload: DamageEventCreate) =>
      request<DamageEventCreateResult>(`/battles/${battleId}/damage-events`, {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    createResourceEvent: (battleId: string, payload: ResourceChangeEventCreate) =>
      request<Record<string, unknown>>(`/battles/${battleId}/resource-events`, {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    createEvent: (battleId: string, payload: BattleEventCreate) =>
      request<BattleEventOut>(`/battles/${battleId}/events`, {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    createSkillEvent: (battleId: string, payload: SkillUseEventCreate) =>
      request<BattleEventOut>(`/battles/${battleId}/skill-events`, {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    timeline: (battleId: string) => request<BattleTimelineTurnOut[]>(`/battles/${battleId}/timeline`),
    snapshot: (battleId: string, snapshotId: string) =>
      request<BattleEffectSnapshotOut>(`/battles/${battleId}/snapshots/${snapshotId}`),
    events: (battleId: string) => request<BattleEventOut[]>(`/battles/${battleId}/events`),
    voidEvent: (battleId: string, eventId: string, payload: BattleEventVoidInput) =>
      request<BattleEventOut>(`/battles/${battleId}/events/${eventId}/void`, { method: "POST", body: JSON.stringify(payload) }),
    correctEvent: (battleId: string, eventId: string, payload: BattleEventCorrectInput) =>
      request<BattleEventOut>(`/battles/${battleId}/events/${eventId}/correct`, { method: "POST", body: JSON.stringify(payload) }),
    replayFrom: (battleId: string, eventId: string) =>
      request<BattleReplayResult>(`/battles/${battleId}/replay-from/${eventId}`, { method: "POST" }),
  },

  observations: {
    process: (battleId: string, payload: ObservationCreate) =>
      request<ObservationProcessResult>(`/observations/${battleId}`, {
        method: "POST",
        body: JSON.stringify(payload),
      }),
  },

  estimates: {
    get: (battleId: string, elfId: string) =>
      request<EnemyPanelEstimateOut>(`/estimates/${battleId}/${elfId}`),
    updateDefaultConfig: (
      battleId: string,
      elfId: string,
      payload: EnemyDefaultConfigInput,
    ) =>
      request<EnemyPanelEstimateOut>(`/estimates/${battleId}/${elfId}/default-config`, {
        method: "PUT",
        body: JSON.stringify(payload),
      }),
    evidence: (battleId: string, elfId: string, limit = 50) =>
      request<EnemyPanelEstimateEvidenceOut[]>(
        `/estimates/${battleId}/${elfId}/evidence${qs({ limit })}`,
      ),
  },

  adminBattles: {
    purgePlan: (battleId: string, adminToken?: string) =>
      request<BattlePurgePlanOut>(`/admin/battles/${battleId}/purge-plan`, {
        headers: adminToken ? { "X-Admin-Token": adminToken } : undefined,
      }),
    purgeBattle: (battleId: string, params: { dry_run?: boolean } = {}, adminToken?: string) =>
      request<BattlePurgeResultOut>(`/admin/battles/${battleId}/purge${qs({ dry_run: params.dry_run ?? true })}`, {
        method: "DELETE",
        headers: adminToken ? { "X-Admin-Token": adminToken } : undefined,
      }),
    purgeArchived: (
      params: { dry_run?: boolean; older_than_days?: number | null; limit?: number | null } = {},
      adminToken?: string,
    ) =>
      request<BattlePurgeResultOut>(
        `/admin/battles/purge-archived${qs({
          dry_run: params.dry_run ?? true,
          older_than_days: params.older_than_days,
          limit: params.limit,
        })}`,
        {
          method: "DELETE",
          headers: adminToken ? { "X-Admin-Token": adminToken } : undefined,
        },
      ),
  },

  adminDataUpdates: {
    bootstrapStatus: (params: { cleaned_dir?: string | null } = {}, adminToken?: string) =>
      request<ProjectDataBootstrapStatus>(
        `/admin/data-updates/bootstrap/status${qs({ cleaned_dir: params.cleaned_dir })}`,
        {
          headers: adminToken ? { "X-Admin-Token": adminToken } : undefined,
        },
      ),
    bootstrapImportLocal: (payload: ProjectBootstrapLocalRequest, adminToken?: string) =>
      request<RocomDataUpdateAccepted>("/admin/data-updates/bootstrap/import-local", {
        method: "POST",
        headers: adminToken ? { "X-Admin-Token": adminToken } : undefined,
        body: JSON.stringify(payload),
      }),
    checkRocom: (payload: RocomCheckRequest = {}, adminToken?: string) =>
      request<RocomCheckResponse>("/admin/data-updates/rocom/check", {
        method: "POST",
        headers: adminToken ? { "X-Admin-Token": adminToken } : undefined,
        body: JSON.stringify(payload),
      }),
    syncRocom: (payload: RocomDataUpdateRequest, adminToken?: string) =>
      request<RocomDataUpdateAccepted>("/admin/data-updates/rocom/sync", {
        method: "POST",
        headers: adminToken ? { "X-Admin-Token": adminToken } : undefined,
        body: JSON.stringify(payload),
      }),
    importLocalRocom: (payload: RocomLocalImportRequest, adminToken?: string) =>
      request<RocomDataUpdateAccepted>("/admin/data-updates/rocom/import-local", {
        method: "POST",
        headers: adminToken ? { "X-Admin-Token": adminToken } : undefined,
        body: JSON.stringify(payload),
      }),
    getRocomJob: (jobId: string, adminToken?: string) =>
      request<RocomDataUpdateJobStatus>(`/admin/data-updates/rocom/jobs/${jobId}`, {
        headers: adminToken ? { "X-Admin-Token": adminToken } : undefined,
      }),
    listRocomJobs: (adminToken?: string) =>
      request<RocomDataUpdateJobStatus[]>("/admin/data-updates/rocom/jobs", {
        headers: adminToken ? { "X-Admin-Token": adminToken } : undefined,
      }),
    checkStaticSkillRules: (params: { limit?: number; q?: string | null } = {}, adminToken?: string) =>
      request<StaticSkillRuleSyncResponse>(
        `/admin/data-updates/static-rules/skill-reviews/check${qs({ limit: params.limit ?? 100, q: params.q })}`,
        {
          headers: adminToken ? { "X-Admin-Token": adminToken } : undefined,
        },
      ),
    syncStaticSkillRules: (payload: StaticSkillRuleSyncRequest, adminToken?: string) =>
      request<StaticSkillRuleSyncResponse>("/admin/data-updates/static-rules/skill-reviews/sync", {
        method: "POST",
        headers: adminToken ? { "X-Admin-Token": adminToken } : undefined,
        body: JSON.stringify(payload),
      }),
    syncEvolutionChains: (payload: EvolutionChainSyncRequest, adminToken?: string) =>
      request<EvolutionChainSyncResponse>("/admin/data-updates/static-rules/evolution-chains/sync", {
        method: "POST",
        headers: adminToken ? { "X-Admin-Token": adminToken } : undefined,
        body: JSON.stringify(payload),
      }),
  },

};
