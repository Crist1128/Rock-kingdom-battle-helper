import type {
  BattleCreate,
  BattleEventCorrectInput,
  BattleEventOut,
  BattleEventVoidInput,
  BattleOut,
  BattlePurgePlanOut,
  BattlePurgeResultOut,
  BattleReplayResult,
  BattleStateOut,
  BattleTimelineTurnOut,
  CandidateDetailOut,
  CandidateEvidenceOut,
  CandidateOut,
  CandidateSummaryOut,
  DamageEventCreate,
  EffectApplyInput,
  EffectDefinitionOut,
  ElfDefinitionOut,
  LineupInput,
  LineupOut,
  NatureDefinitionOut,
  PlayerElfBuildCreate,
  PlayerElfBuildOut,
  ResourceChangeEventCreate,
  RocomCheckRequest,
  RocomCheckResponse,
  RocomDataUpdateAccepted,
  RocomDataUpdateJobStatus,
  RocomDataUpdateRequest,
  RocomLocalImportRequest,
  SkillDefinitionOut,
  StartBattleInput,
  SwitchElfInput,
} from "@/types/api";

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : `API request failed: ${status}`);
    this.status = status;
    this.detail = detail;
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
    let detail: unknown = response.statusText;
    try {
      detail = await response.json();
    } catch {
      // keep response.statusText
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) return undefined as T;
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

  elves: {
    list: (params: { q?: string; limit?: number; offset?: number } = {}) =>
      request<ElfDefinitionOut[]>(`/elves${qs({ limit: 50, ...params })}`),
    get: (elfId: string) => request<ElfDefinitionOut>(`/elves/${elfId}`),
    skills: (elfId: string, params: { q?: string; limit?: number; offset?: number } = {}) =>
      request<SkillDefinitionOut[]>(`/elves/${elfId}/skills${qs({ limit: 500, ...params })}`),
  },

  skills: {
    list: (params: { q?: string; limit?: number; offset?: number } = {}) =>
      request<SkillDefinitionOut[]>(`/skills${qs({ limit: 50, ...params })}`),
    get: (skillId: string) => request<SkillDefinitionOut>(`/skills/${skillId}`),
  },

  natures: {
    list: (params: { q?: string; limit?: number; offset?: number } = {}) =>
      request<NatureDefinitionOut[]>(`/natures${qs({ limit: 100, ...params })}`),
    get: (natureId: string) => request<NatureDefinitionOut>(`/natures/${natureId}`),
  },

  effects: {
    list: (params: { q?: string; category?: string; owner_scope?: string; limit?: number; offset?: number } = {}) =>
      request<EffectDefinitionOut[]>(`/effects${qs({ limit: 80, ...params })}`),
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
    finish: (battleId: string) =>
      request<BattleOut>(`/battles/${battleId}/finish`, { method: "POST" }),
    archive: (battleId: string) =>
      request<BattleOut>(`/battles/${battleId}/archive`, { method: "POST" }),
    createDamageEvent: (battleId: string, payload: DamageEventCreate) =>
      request<Record<string, unknown>>(`/battles/${battleId}/damage-events`, {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    createResourceEvent: (battleId: string, payload: ResourceChangeEventCreate) =>
      request<Record<string, unknown>>(`/battles/${battleId}/resource-events`, {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    timeline: (battleId: string) => request<BattleTimelineTurnOut[]>(`/battles/${battleId}/timeline`),
    events: (battleId: string) => request<BattleEventOut[]>(`/battles/${battleId}/events`),
    voidEvent: (battleId: string, eventId: string, payload: BattleEventVoidInput) =>
      request<BattleEventOut>(`/battles/${battleId}/events/${eventId}/void`, { method: "POST", body: JSON.stringify(payload) }),
    correctEvent: (battleId: string, eventId: string, payload: BattleEventCorrectInput) =>
      request<BattleEventOut>(`/battles/${battleId}/events/${eventId}/correct`, { method: "POST", body: JSON.stringify(payload) }),
    replayFrom: (battleId: string, eventId: string) =>
      request<BattleReplayResult>(`/battles/${battleId}/replay-from/${eventId}`, { method: "POST" }),
  },

  candidates: {
    summary: (battleId: string, elfId: string) =>
      request<CandidateSummaryOut>(`/candidates/${battleId}/${elfId}/summary`),
    detail: (battleId: string, elfId: string, includeExcluded = false) =>
      request<CandidateDetailOut>(`/candidates/${battleId}/${elfId}/detail${qs({ include_excluded: includeExcluded })}`),
    evidence: (battleId: string, elfId: string) =>
      request<CandidateEvidenceOut>(`/candidates/${battleId}/${elfId}/evidence`),
    list: (battleId: string, elfId: string, params: { limit?: number; offset?: number; include_excluded?: boolean } = {}) =>
      request<CandidateOut[]>(`/candidates/${battleId}/${elfId}${qs({ limit: 50, offset: 0, ...params })}`),
    generate: (battleId: string, elfId: string) =>
      request<CandidateSummaryOut>(`/candidates/${battleId}/${elfId}/generate`, { method: "POST" }),
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
  },

};
