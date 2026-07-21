import { lazy, Suspense, type ComponentType, type LazyExoticComponent } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "@/components/Layout";
import { PageLoadingSkeleton } from "@/components/ui/skeleton";

/** 页面均为具名导出，这里统一包一层转 default 并挂路由级加载骨架。 */
function lazyPage<T extends ComponentType<object>>(
  factory: () => Promise<{ [key: string]: T }>,
  exportName: string,
): LazyExoticComponent<T> {
  return lazy(() => factory().then((module) => ({ default: module[exportName] })));
}

const DashboardPage = lazyPage(() => import("@/pages/DashboardPage"), "DashboardPage");
const PlayerBuildsPage = lazyPage(() => import("@/pages/PlayerBuildsPage"), "PlayerBuildsPage");
const PreparationPage = lazyPage(() => import("@/pages/PreparationPage"), "PreparationPage");
const BattleWorkbenchPage = lazyPage(() => import("@/pages/BattleWorkbenchPage"), "BattleWorkbenchPage");
const DamageCalculatorPage = lazyPage(() => import("@/pages/DamageCalculatorPage"), "DamageCalculatorPage");
const EventLogPage = lazyPage(() => import("@/pages/EventLogPage"), "EventLogPage");
const RulesPage = lazyPage(() => import("@/pages/RulesPage"), "RulesPage");
const SettingsPage = lazyPage(() => import("@/pages/SettingsPage"), "SettingsPage");

function page(element: React.ReactNode) {
  return <Suspense fallback={<PageLoadingSkeleton />}>{element}</Suspense>;
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={page(<DashboardPage />)} />
        <Route path="builds" element={page(<PlayerBuildsPage />)} />
        <Route path="preparation" element={page(<PreparationPage />)} />
        <Route path="battle" element={page(<BattleWorkbenchPage />)} />
        <Route path="damage-calculator" element={page(<DamageCalculatorPage />)} />
        <Route path="events" element={page(<EventLogPage />)} />
        <Route path="rules" element={page(<RulesPage />)} />
        <Route path="settings" element={page(<SettingsPage />)} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
