import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "@/components/Layout";
import { DashboardPage } from "@/pages/DashboardPage";
import { PlayerBuildsPage } from "@/pages/PlayerBuildsPage";
import { PreparationPage } from "@/pages/PreparationPage";
import { BattleWorkbenchPage } from "@/pages/BattleWorkbenchPage";
import { EventLogPage } from "@/pages/EventLogPage";
import { RulesPage } from "@/pages/RulesPage";
import { SettingsPage } from "@/pages/SettingsPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="builds" element={<PlayerBuildsPage />} />
        <Route path="preparation" element={<PreparationPage />} />
        <Route path="battle" element={<BattleWorkbenchPage />} />
        <Route path="events" element={<EventLogPage />} />
        <Route path="rules" element={<RulesPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
