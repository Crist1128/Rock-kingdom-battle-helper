import { NavLink, Outlet } from "react-router-dom";
import { Activity, Database, Home, ListChecks, Settings, Shield, Sword } from "lucide-react";
import { cn } from "@/lib/utils";
import { FormulaUnavailableBanner } from "./FormulaUnavailableBanner";

const navItems = [
  { to: "/builds", label: "己方配置", icon: Shield },
  { to: "/", label: "战斗", icon: Home },
  { to: "/preparation", label: "准备阶段", icon: ListChecks },
  { to: "/battle", label: "战斗工作台", icon: Sword },
  { to: "/events", label: "事件日志", icon: Activity },
  { to: "/rules", label: "规则库", icon: Database },
  { to: "/settings", label: "设置", icon: Settings },
];

export function Layout() {
  return (
    <div className="flex min-h-screen bg-slate-50">
      <aside className="sticky top-0 h-screen w-64 border-r bg-white p-4">
        <div className="mb-6 rounded-2xl bg-slate-950 p-4 text-white">
          <div className="text-sm text-slate-300">Rock PVP Helper</div>
          <div className="mt-1 text-lg font-semibold">前端 MVP</div>
        </div>
        <nav className="space-y-1">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition",
                    isActive ? "bg-primary text-primary-foreground" : "text-slate-700 hover:bg-slate-100",
                  )
                }
              >
                <Icon className="h-4 w-4" />
                {item.label}
              </NavLink>
            );
          })}
        </nav>
        <div className="absolute bottom-4 left-4 right-4 rounded-2xl border bg-slate-50 p-3 text-xs text-muted-foreground">
          本地手动输入模式。不会自动识图，不会自动推荐出招。
        </div>
      </aside>
      <main className="flex-1 p-6">
        <FormulaUnavailableBanner />
        <Outlet />
      </main>
    </div>
  );
}
