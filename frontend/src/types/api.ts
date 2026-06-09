export type Side = "self" | "enemy";
export type BattlePhase = "preparation" | "battle" | "finished" | "archived";
export type DamageDisplayType = "single_damage" | "visual_total_damage" | "combo_repeated_damage" | "special_damage";

export interface StatBlock {
  hp: number | null;
  physical_attack: number | null;
  physical_defense: number | null;
  magic_attack: number | null;
  magic_defense: number | null;
  speed: number | null;
}

export interface ElfDefinitionOut {
  elf_id: string;
  elf_name: string;
  avatar: string;
  element_types_json: string;
  base_hp_talent: number;
  base_physical_attack_talent: number;
  base_physical_defense_talent: number;
  base_magic_attack_talent: number;
  base_magic_defense_talent: number;
  base_speed_talent: number;
  data_version?: string | null;
}

export interface SkillDefinitionOut {
  skill_id: string;
  skill_name: string;
  skill_icon?: string | null;
  element_type: string;
  skill_category: string;
  base_power?: number | null;
  base_energy_cost: number;
  priority_modifier: number;
  damage_rule_json?: string | null;
  hit_rule_json?: string | null;
  effect_operations_json?: string | null;
}

export interface NatureDefinitionOut {
  nature_id: string;
  nature_name: string;
  positive_stat: string;
  positive_multiplier: number;
  negative_stat: string;
  negative_multiplier: number;
  neutral_multiplier: number;
}

export interface EffectDefinitionOut {
  effect_id: string;
  effect_name: string;
  icon?: string | null;
  category: string;
  polarity: string;
  display_group: string;
  display_priority: number;
  owner_scope: string;
  target_scope: string;
  attach_target_type: string;
  is_visible_icon: boolean;
  is_recognizable_by_icon: boolean;
  recognition_alias_json?: string | null;
  default_layers: number;
  max_layers?: number | null;
  stack_rule: string;
  refresh_rule?: string | null;
  duration_type: string;
  default_duration_turns?: number | null;
  default_duration_uses?: number | null;
  clear_on_switch: boolean;
  clear_by_abnormal_cleanse: boolean;
  clear_by_stat_clear: boolean;
  clear_by_mark_clear: boolean;
  clear_by_weather_replace: boolean;
  clear_by_skill_specific: boolean;
  can_be_transferred: boolean;
  can_be_converted: boolean;
  can_be_inherited: boolean;
  can_be_stolen: boolean;
  can_be_doubled: boolean;
  conflict_group?: string | null;
  conflict_policy?: string | null;
  formula_hooks_json?: string | null;
  stat_modifier_json?: string | null;
  damage_modifier_json?: string | null;
  skill_modifier_json?: string | null;
  action_modifier_json?: string | null;
  resource_modifier_json?: string | null;
  special_rule_id?: string | null;
  developer_notes?: string | null;
  data_version?: string | null;
}

export interface IndividualTalentInput {
  hp: number;
  physical_attack: number;
  physical_defense: number;
  magic_attack: number;
  magic_defense: number;
  speed: number;
}

export interface PlayerElfBuildCreate {
  elf_id: string;
  nature_id: string;
  individual_talent_distribution: IndividualTalentInput;
  skill_ids: string[];
  build_name?: string | null;
  is_default?: boolean;
  notes?: string | null;
}

export interface PlayerElfBuildOut {
  build_id: string;
  build_name?: string | null;
  elf_id: string;
  /**
   * 后端为配置列表和准备阶段下拉框冗余返回的中文精灵名。
   * 旧后端可能没有该字段，因此前端仍保留 elf_id 兜底。
   */
  elf_name?: string | null;
  avatar?: string | null;
  element_types_json?: string | null;
  nature_id: string;
  individual_talent_distribution_json: string;
  final_stats_json?: string | null;
  skill_ids: string[];
  is_default: boolean;
  notes?: string | null;
}

export interface EnemyDefaultConfigInput {
  preset?: string;
  nature_id: string;
  individual_talent_distribution: IndividualTalentInput;
}

export interface EnemyPanelEstimateOut {
  estimate_id: string;
  battle_id: string;
  battle_elf_state_id: string;
  elf_id: string;
  default_config?: Record<string, unknown> | null;
  default_panel?: Record<string, unknown> | null;
  estimated_panel?: Record<string, unknown> | null;
  stat_constraints: Record<string, unknown>;
  confidence: Record<string, unknown>;
  unknown_factors: string[];
  confirmed_skill_ids: string[];
  evidence_summary: Record<string, unknown>[];
  updated_by_event_id?: string | null;
}

export interface EnemyPanelEstimateEvidenceOut {
  evidence_id: string;
  estimate_id: string;
  battle_id: string;
  source_event_id: string;
  observation_type: string;
  inferred_stats?: Record<string, unknown> | null;
  constraint_delta?: Record<string, unknown> | null;
  formula_context?: Record<string, unknown> | null;
  unknown_factors: string[];
  conflict?: Record<string, unknown> | null;
  confidence?: string | null;
}

export type TeamPresetSideUsage = "self" | "enemy" | "both";
export type TeamPresetSourceType = "custom" | "popular";

export interface TeamPresetSlotInput {
  slot_index: number;
  elf_id: string;
  build_id?: string | null;
  notes?: string | null;
}

export interface TeamPresetCreate {
  preset_name: string;
  side_usage?: TeamPresetSideUsage;
  source_type?: TeamPresetSourceType;
  notes?: string | null;
  slots: TeamPresetSlotInput[];
}

export interface TeamPresetSlotOut {
  slot_id: string;
  preset_id: string;
  slot_index: number;
  elf_id: string;
  elf_name?: string | null;
  avatar?: string | null;
  element_types_json?: string | null;
  build_id?: string | null;
  build_name?: string | null;
  notes?: string | null;
}

export interface TeamPresetOut {
  preset_id: string;
  preset_name: string;
  side_usage: TeamPresetSideUsage;
  source_type: TeamPresetSourceType;
  notes?: string | null;
  slots: TeamPresetSlotOut[];
  created_at?: string | null;
  updated_at?: string | null;
}

export interface BattleCreate {
  battle_name?: string | null;
  notes?: string | null;
}

export interface BattleOut {
  battle_id: string;
  battle_name?: string | null;
  phase: BattlePhase;
  turn_number: number;
  self_active_elf_id?: string | null;
  enemy_active_elf_id?: string | null;
  current_snapshot_id?: string | null;
  notes?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface BattleElfStateDict {
  state_id?: string;
  battle_id: string;
  side: Side;
  elf_id: string;
  elf_name?: string | null;
  avatar?: string | null;
  panel_stats_json?: string | null;
  current_hp_value?: number | null;
  current_hp_percent?: number | null;
  energy?: number | null;
  skill_ids_json?: string | null;
  confirmed_skill_ids_json?: string | null;
  active_effect_instance_ids_json?: string | null;
  is_active_elf?: boolean;
  is_defeated?: boolean;
  last_switch_turn?: number | null;
  manual_override?: boolean;
  [key: string]: unknown;
}

export interface BattleEffectInstanceDict {
  instance_id: string;
  battle_id: string;
  effect_id: string;
  category: string;
  owner_scope: string;
  owner_side?: Side | null;
  owner_elf_id?: string | null;
  owner_skill_slot_id?: string | null;
  field_id?: string | null;
  source_side?: Side | null;
  source_elf_id?: string | null;
  source_skill_id?: string | null;
  layers?: number;
  remaining_turns?: number | null;
  remaining_uses?: number | null;
  is_active?: boolean;
  applied_turn?: number | null;
  expire_turn?: number | null;
  last_updated_turn?: number | null;
  notes?: string | null;
  [key: string]: unknown;
}

export interface BattleStateOut {
  battle: BattleOut;
  elves: BattleElfStateDict[];
  active_effects: BattleEffectInstanceDict[];
  latest_snapshot_id?: string | null;
}

export interface LineupElfInput {
  side: Side;
  elf_id: string;
  build_id?: string | null;
  is_active_elf?: boolean;
}

export interface LineupInput {
  elves: LineupElfInput[];
}

export interface LineupOut {
  battle_id: string;
  created_elf_state_count: number;
  generated_candidate_count: number;
  self_active_elf_id?: string | null;
  enemy_active_elf_id?: string | null;
}

export interface StartBattleInput {
  self_active_elf_id?: string | null;
  enemy_active_elf_id?: string | null;
}

export interface SwitchElfInput {
  side: Side;
  elf_id: string;
  turn_number?: number | null;
  notes?: string | null;
}

export interface EndTurnInput {
  notes?: string | null;
}

export interface EndTurnResult {
  battle: BattleOut;
  battle_event: BattleEventOut;
  ended_turn_number: number;
  next_turn_number: number;
  snapshot_id: string;
  settlement_status: "not_implemented" | "settled" | "partial" | string;
  settlement_events: Record<string, unknown>[];
}

export interface DamageEventCreate {
  turn_number?: number | null;
  attacker_side?: Side | null;
  attacker_elf_id?: string | null;
  defender_side?: Side | null;
  defender_elf_id?: string | null;
  skill_id?: string | null;
  skill_confirmed?: boolean;
  defense_skill_id?: string | null;
  response_attack_success?: boolean | null;
  response_defense_success?: boolean | null;
  response_status_success?: boolean | null;
  damage_display_type: DamageDisplayType;
  damage_value?: number | null;
  final_total_damage_value?: number | null;
  per_hit_damage_value?: number | null;
  hit_count?: number | null;
  combo_count_source?: string | null;
  combo_confidence?: number | null;
  hp_percent_before?: number | null;
  hp_percent_after?: number | null;
  hp_value_before?: number | null;
  hp_value_after?: number | null;
  enemy_hp_percent_damage?: number | null;
  sync_observation?: boolean;
  allow_hard_exclude?: boolean;
  damage_tolerance?: number;
  percent_tolerance?: number;
  notes?: string | null;
}

export interface DamageEventOut {
  event_id: string;
  battle_id: string;
  battle_event_id: string;
  attacker_side?: Side | null;
  attacker_elf_id?: string | null;
  defender_side?: Side | null;
  defender_elf_id?: string | null;
  skill_id?: string | null;
  damage_display_type: string;
  damage_value?: number | null;
  final_total_damage_value?: number | null;
  per_hit_damage_value?: number | null;
  hit_count?: number | null;
  computed_total_damage_value?: number | null;
  hp_percent_before?: number | null;
  hp_percent_after?: number | null;
  hp_percent_delta?: number | null;
  enemy_hp_percent_damage?: number | null;
  formula_context_json?: string | null;
  calculation_confidence?: number | null;
  manual_override: boolean;
}

export interface DamageEventCreateResult {
  battle_event: BattleEventOut;
  damage_event: DamageEventOut;
  snapshot_id: string;
  inference_result: Record<string, unknown>;
  post_settlement_events: Record<string, unknown>[];
}

export interface ResourceChangeEventCreate {
  turn_number?: number | null;
  resource_type: "hp" | "energy" | string;
  change_type: string;
  source_side?: Side | null;
  source_elf_id?: string | null;
  target_side?: Side | null;
  target_elf_id?: string | null;
  skill_id?: string | null;
  value_type: "value" | "percent" | string;
  value: number;
  before_value?: number | null;
  after_value?: number | null;
  confidence?: number | null;
  notes?: string | null;
}

export interface EffectApplyInput {
  effect_id: string;
  battle_id: string;
  owner_scope: string;
  owner_side?: Side | null;
  owner_elf_id?: string | null;
  owner_skill_slot_id?: string | null;
  field_id?: string | null;
  source_side?: Side | null;
  source_elf_id?: string | null;
  source_skill_id?: string | null;
  turn_number?: number | null;
  layers?: number | null;
  remaining_turns?: number | null;
  remaining_uses?: number | null;
  notes?: string | null;
}



export type ObservationType =
  | "damage_value"
  | "hp_percent_delta"
  | "speed_order"
  | "skill_seen"
  | "state_trigger"
  | "survival";

export interface PanelStatsInput {
  hp: number;
  physical_attack: number;
  physical_defense: number;
  magic_attack: number;
  magic_defense: number;
  speed: number;
}

export interface ObservationPayloadV1 {
  schema_version: "observation_payload_v1";
  context_kind: "damage" | "skill" | "speed" | "state" | "survival";
  roles?: {
    enemy_role?: "attacker" | "defender";
  };
  participants?: {
    attacker_side?: Side | null;
    attacker_elf_id?: string | null;
    defender_side?: Side | null;
    defender_elf_id?: string | null;
  };
  panels?: {
    attacker?: PanelStatsInput | null;
    defender?: PanelStatsInput | null;
    defender_max_hp?: number | null;
  };
  skill?: {
    skill_id?: string | null;
    defense_skill_id?: string | null;
    skill_category?: string | null;
    skill_element_type?: string | null;
    trigger_skill_id?: string | null;
    trigger_skill_element_type?: string | null;
    trigger_skill_category?: string | null;
  };
  response?: {
    attack_success?: boolean | null;
    defense_success?: boolean | null;
    status_success?: boolean | null;
  };
  formula?: Record<string, unknown>;
  effects?: Record<string, unknown>;
  observed?: Record<string, unknown>;
  matching?: Record<string, unknown>;
}

export interface ObservationCreate {
  enemy_elf_id: string;
  event_id?: string | null;
  observation_type: ObservationType;
  observed_value?: number | string | null;
  payload?: ObservationPayloadV1 | Record<string, unknown>;
  event_weight?: number | null;
  allow_hard_exclude?: boolean;
}

export interface ObservationProcessResult {
  status: string;
  battle_id: string;
  enemy_elf_id: string;
  event_id: string;
  observation_type: string;
  estimate_id?: string | null;
  inferred_stat_count: number;
  affected_stats: string[];
  unknown_factor_count: number;
  hard_filter_applied: boolean;
}

export interface BattleEventOut {
  event_id: string;
  battle_id: string;
  turn_number: number;
  action_order?: number | null;
  event_type: string;
  actor_side?: Side | null;
  actor_elf_id?: string | null;
  target_side?: Side | null;
  target_elf_id?: string | null;
  skill_id?: string | null;
  skill_confirmed: boolean;
  snapshot_id?: string | null;
  source: string;
  recognition_confidence?: number | null;
  manual_override: boolean;
  corrected_event_id?: string | null;
  is_voided: boolean;
  payload_json?: string | null;
  notes?: string | null;
}

export interface BattleEventCreate {
  turn_number: number;
  event_type: string;
  action_order?: number | null;
  actor_side?: Side | null;
  actor_elf_id?: string | null;
  target_side?: Side | null;
  target_elf_id?: string | null;
  skill_id?: string | null;
  skill_confirmed?: boolean;
  snapshot_id?: string | null;
  source?: string;
  recognition_confidence?: number | null;
  manual_override?: boolean;
  corrected_event_id?: string | null;
  is_voided?: boolean;
  payload_json?: string | null;
  notes?: string | null;
}

export interface SkillUseEventCreate {
  turn_number?: number | null;
  action_order?: number | null;
  actor_side?: Side | null;
  actor_elf_id?: string | null;
  target_side?: Side | null;
  target_elf_id?: string | null;
  skill_id: string;
  skill_confirmed?: boolean;
  condition_flags?: Record<string, boolean> | null;
  manual_flags?: Record<string, boolean> | null;
  notes?: string | null;
}

export interface BattleTimelineEventOut {
  event: BattleEventOut;
  detail_type?: string | null;
  detail: Record<string, unknown>;
}

export interface BattleTimelineTurnOut {
  turn_number: number;
  events: BattleTimelineEventOut[];
}


export interface BattleEventVoidInput {
  reason?: string | null;
  create_audit_event?: boolean;
}

export interface BattleEventCorrectInput {
  replacement_event: {
    turn_number: number;
    event_type: string;
    action_order?: number | null;
    actor_side?: Side | null;
    actor_elf_id?: string | null;
    target_side?: Side | null;
    target_elf_id?: string | null;
    skill_id?: string | null;
    skill_confirmed?: boolean;
    source?: string;
    recognition_confidence?: number | null;
    manual_override?: boolean;
    payload_json?: string | null;
    notes?: string | null;
  };
  reason?: string | null;
  void_original?: boolean;
}

export interface BattleReplayResult {
  battle_id: string;
  from_event_id: string;
  status: string;
  message: string;
}

export interface BattleEffectSnapshotOut {
  snapshot_id: string;
  battle_id: string;
  turn_number: number;
  active_effect_instance_ids_json: string;
  self_active_elf_id?: string | null;
  enemy_active_elf_id?: string | null;
  self_elf_effect_ids_json?: string | null;
  enemy_elf_effect_ids_json?: string | null;
  self_side_effect_ids_json?: string | null;
  enemy_side_effect_ids_json?: string | null;
  field_effect_ids_json?: string | null;
  skill_slot_effect_ids_json?: string | null;
  turn_effect_ids_json?: string | null;
  full_snapshot_json?: string | null;
  source_event_id?: string | null;
}

export interface BattlePurgePlanOut {
  battle_id: string;
  battle_name?: string | null;
  phase?: string | null;
  can_purge: boolean;
  reason?: string | null;
  rows: Record<string, number>;
}

export interface BattlePurgeResultOut {
  dry_run: boolean;
  battle_count: number;
  battle_ids: string[];
  rows: Record<string, number>;
  message: string;
}


export interface RocomCheckRequest {
  /** 只检查前 N 条；0 表示全量。 */
  limit?: number;
  /** 响应中最多返回多少条新增精灵预览。 */
  include_new_elves_limit?: number;
}

export interface RocomCheckResponse {
  source: string;
  status: "changed" | "unchanged";
  checked_at: string;
  remote_count: number;
  local_rocom_count: number;
  new_elf_count: number;
  missing_local_count: number;
  new_elves: Array<Record<string, unknown>>;
  new_elves_truncated: boolean;
  remote_fingerprint: string;
  note: string;
}

export interface RocomDataUpdateRequest {
  /** 是否实际提交数据库事务；false 为 dry-run。 */
  commit?: boolean;
  /** 是否强制重新爬取已缓存精灵。 */
  force?: boolean;
  /** 只更新前 N 条；0 表示全量。 */
  limit?: number;
  /** 爬虫请求间隔下限秒数。 */
  delay?: number;
  /** 是否下载图片；MVP 默认仅记录远程图片 URL。 */
  with_images?: boolean;
  /** 可选规则数据版本号，例如 rocom_bwiki_20260516。 */
  data_version?: string | null;
  /** 是否写 raw/cleaned JSON 文件便于审阅。 */
  write_artifacts?: boolean;
}

export interface RocomLocalImportRequest {
  /** cleaned JSON 目录；留空时使用后端 ROCOM_DATA_DIR/cleaned。 */
  cleaned_dir?: string | null;
  /** 是否实际提交数据库事务；false 为 dry-run。 */
  commit?: boolean;
  /** 可选：覆盖 cleaned 数据中的 data_version。 */
  data_version?: string | null;
}

export interface RocomDataUpdateAccepted {
  job_id: string;
  status: "queued" | "running" | "succeeded" | "failed";
  message: string;
}

export interface RocomDataUpdateJobStatus {
  job_id: string;
  status: "queued" | "running" | "succeeded" | "failed";
  created_at: string;
  job_type: string;
  started_at?: string | null;
  finished_at?: string | null;
  params: Record<string, unknown>;
  result?: Record<string, unknown> | null;
  error?: string | null;
}
