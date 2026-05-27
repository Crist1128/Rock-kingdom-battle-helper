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
  category: string;
  polarity: string;
  display_group: string;
  owner_scope: string;
  clear_on_switch: boolean;
  formula_hooks_json?: string | null;
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

export interface DamageEventCreate {
  turn_number?: number | null;
  attacker_side?: Side | null;
  attacker_elf_id?: string | null;
  defender_side?: Side | null;
  defender_elf_id?: string | null;
  skill_id?: string | null;
  skill_confirmed?: boolean;
  damage_display_type: DamageDisplayType;
  damage_value?: number | null;
  final_total_damage_value?: number | null;
  per_hit_damage_value?: number | null;
  hit_count?: number | null;
  combo_count_source?: string | null;
  combo_confidence?: number | null;
  hp_percent_before?: number | null;
  hp_percent_after?: number | null;
  enemy_hp_percent_damage?: number | null;
  notes?: string | null;
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

export interface ObservationCreate {
  enemy_elf_id: string;
  event_id?: string | null;
  observation_type: ObservationType;
  observed_value?: number | string | null;
  payload?: Record<string, unknown>;
  event_weight?: number | null;
  allow_hard_exclude?: boolean;
}

export interface ObservationProcessResult {
  status: string;
  battle_id: string;
  enemy_elf_id: string;
  event_id: string;
  observation_type: string;
  candidate_count: number;
  matched_count: number;
  mismatched_count: number;
  unknown_count: number;
  hard_excluded_count: number;
  hard_filter_applied: boolean;
  top_candidate_id?: string | null;
  top_confidence?: number | null;
}

export interface CandidateSummaryOut {
  battle_id: string;
  elf_id: string;
  total_count: number;
  active_count: number;
  excluded_count: number;
  min_speed?: number | null;
  max_speed?: number | null;
  top_confidence?: number | null;
  formula_status: string;
}

export interface CandidateOut {
  candidate_id: string;
  battle_id: string;
  side: Side;
  elf_id: string;
  nature_id: string;
  individual_talent_distribution_json: string;
  final_hp: number;
  final_physical_attack: number;
  final_physical_defense: number;
  final_magic_attack: number;
  final_magic_defense: number;
  final_speed: number;
  possible_skill_ids_json?: string | null;
  confirmed_skill_ids_json?: string | null;
  match_score: number;
  confidence: number;
  is_excluded: boolean;
  excluded_reason?: string | null;
}

export interface CandidateNatureDistributionItem {
  nature_id: string;
  count: number;
  ratio: number;
}

export interface CandidateTalentDistributionItem {
  stat_key: string;
  non_zero_count: number;
  zero_count: number;
  value_counts: Record<string, number>;
}

export interface CandidatePatternDistributionItem {
  pattern: string;
  count: number;
  ratio: number;
}

export interface CandidateSpeedBucketItem {
  min_speed: number;
  max_speed: number;
  count: number;
  ratio: number;
}

export interface CandidateDetailOut {
  summary: CandidateSummaryOut;
  speed_buckets: CandidateSpeedBucketItem[];
  nature_distribution: CandidateNatureDistributionItem[];
  talent_distribution: CandidateTalentDistributionItem[];
  pattern_distribution: CandidatePatternDistributionItem[];
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

export interface CandidateEvidenceOut {
  battle_id: string;
  elf_id: string;
  formula_status: string;
  evidence_items: Record<string, unknown>[];
  message: string;
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
