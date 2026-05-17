import { create } from "zustand";
import type { Side } from "@/types/api";

export type DrawerMode = "damage" | "resource" | "effect" | "switch" | null;

interface RecentBattle {
  battle_id: string;
  battle_name?: string | null;
  phase?: string | null;
  updated_at: string;
}

interface AppState {
  currentBattleId: string | null;
  activeDrawer: DrawerMode;
  drawerSide: Side | null;
  selectedEventId: string | null;
  candidatePanelElfId: string | null;
  recentBattles: RecentBattle[];
  setCurrentBattleId: (battleId: string | null) => void;
  openDrawer: (mode: DrawerMode, side?: Side | null) => void;
  closeDrawer: () => void;
  setSelectedEventId: (eventId: string | null) => void;
  setCandidatePanelElfId: (elfId: string | null) => void;
  addRecentBattle: (battle: { battle_id: string; battle_name?: string | null; phase?: string | null }) => void;
  removeRecentBattle: (battleId: string) => void;
}

const storageKey = "rock-pvp-helper.recentBattles";

function loadRecentBattles(): RecentBattle[] {
  try {
    return JSON.parse(localStorage.getItem(storageKey) ?? "[]") as RecentBattle[];
  } catch {
    return [];
  }
}

function saveRecentBattles(items: RecentBattle[]) {
  localStorage.setItem(storageKey, JSON.stringify(items.slice(0, 20)));
}

export const useAppStore = create<AppState>((set, get) => ({
  currentBattleId: localStorage.getItem("rock-pvp-helper.currentBattleId"),
  activeDrawer: null,
  drawerSide: null,
  selectedEventId: null,
  candidatePanelElfId: null,
  recentBattles: loadRecentBattles(),
  setCurrentBattleId: (battleId) => {
    if (battleId) localStorage.setItem("rock-pvp-helper.currentBattleId", battleId);
    else localStorage.removeItem("rock-pvp-helper.currentBattleId");
    set({ currentBattleId: battleId });
  },
  openDrawer: (mode, side = null) => set({ activeDrawer: mode, drawerSide: side }),
  closeDrawer: () => set({ activeDrawer: null, drawerSide: null }),
  setSelectedEventId: (eventId) => set({ selectedEventId: eventId }),
  setCandidatePanelElfId: (elfId) => set({ candidatePanelElfId: elfId }),
  addRecentBattle: (battle) => {
    const next = [
      { ...battle, updated_at: new Date().toISOString() },
      ...get().recentBattles.filter((item) => item.battle_id !== battle.battle_id),
    ].slice(0, 20);
    saveRecentBattles(next);
    set({ recentBattles: next, currentBattleId: battle.battle_id });
    localStorage.setItem("rock-pvp-helper.currentBattleId", battle.battle_id);
  },
  removeRecentBattle: (battleId) => {
    const next = get().recentBattles.filter((item) => item.battle_id !== battleId);
    saveRecentBattles(next);
    set({ recentBattles: next });
  },
}));
