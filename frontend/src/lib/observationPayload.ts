import type { ObservationPayloadV1, PanelStatsInput, Side } from "@/types/api";

export interface DamageObservationPayloadInput {
  resolveRules: boolean;
  attackerSide: Side;
  defenderSide: Side;
  attackerElfId?: string | null;
  defenderElfId?: string | null;
  attackerPanelStats?: PanelStatsInput | null;
  defenderPanelStats?: PanelStatsInput | null;
  skillId?: string | null;
  defenseSkillId?: string | null;
  responseAttackSuccess?: boolean | null;
  responseDefenseSuccess?: boolean | null;
  responseStatusSuccess?: boolean | null;
  observedDamageValue: number;
  damageTolerance: number;
  hitCount: number;
}

export function buildDamageObservationPayloadV1(
  input: DamageObservationPayloadInput,
): ObservationPayloadV1 {
  const enemyIsAttacker = input.attackerSide === "enemy";
  return compactPayload({
    schema_version: "observation_payload_v1",
    context_kind: "damage",
    roles: { enemy_role: enemyIsAttacker ? "attacker" : "defender" },
    participants: compactPayload({
      attacker_side: input.attackerSide,
      attacker_elf_id: input.attackerElfId,
      defender_side: input.defenderSide,
      defender_elf_id: input.defenderElfId,
    }),
    panels: compactPayload({
      attacker: input.attackerPanelStats,
      defender: input.defenderPanelStats,
    }),
    skill: compactPayload({
      skill_id: input.skillId,
      defense_skill_id: input.defenseSkillId,
    }),
    response: compactPayload({
      attack_success: input.responseAttackSuccess,
      defense_success: input.responseDefenseSuccess,
      status_success: input.responseStatusSuccess,
    }),
    formula: {
      formula_type: "attack",
      resolve_rules: input.resolveRules,
      hit_count: input.hitCount,
    },
    observed: {
      damage_value: input.observedDamageValue,
    },
    matching: {
      damage_tolerance: input.damageTolerance,
    },
  }) as ObservationPayloadV1;
}

function compactPayload<T extends Record<string, unknown>>(value: T): Partial<T> {
  return Object.fromEntries(
    Object.entries(value).filter(([, item]) => {
      if (item === undefined || item === null) return false;
      if (typeof item === "object" && !Array.isArray(item) && Object.keys(item).length === 0) {
        return false;
      }
      return true;
    }),
  ) as Partial<T>;
}
