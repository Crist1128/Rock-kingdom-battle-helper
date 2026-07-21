import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  Calculator,
  ChevronDown,
  ChevronsLeft,
  ChevronsRight,
  Database,
  Home,
  ListChecks,
  Moon,
  Settings,
  Shield,
  Sparkles,
  Sun,
  Sword,
} from "lucide-react";
import { api } from "@/lib/api";
import { cn, compactId, phaseName } from "@/lib/utils";
import { useAppStore } from "@/store/useAppStore";
import { FormulaUnavailableBanner } from "./FormulaUnavailableBanner";

const primaryNavItems = [
  { to: "/builds", label: "己方配置", icon: Shield },
  { to: "/", label: "战斗", icon: Home },
  { to: "/preparation", label: "准备阶段", icon: ListChecks },
  { to: "/battle", label: "战斗工作台", icon: Sword },
];

const toolNavItems = [
  { to: "/damage-calculator", label: "伤害计算器", icon: Calculator },
  { to: "/starfall-calculator", label: "星陨伤害计算器", icon: Sparkles },
];

const secondaryNavItems = [
  { to: "/events", label: "事件日志", icon: Activity },
  { to: "/rules", label: "规则库", icon: Database },
  { to: "/settings", label: "设置", icon: Settings },
];

const COLLAPSE_STORAGE_KEY = "rock-pvp-helper.sidebarCollapsed";
const THEME_STORAGE_KEY = "rock-pvp-helper.theme";

export function Layout() {
  const location = useLocation();
  const themeAnimationTimerRef = useRef<number | null>(null);
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem(COLLAPSE_STORAGE_KEY) === "1",
  );
  const [toolsExpanded, setToolsExpanded] = useState(() =>
    toolNavItems.some((item) => item.to === location.pathname),
  );
  const [isDark, setIsDark] = useState(() => document.documentElement.classList.contains("dark"));

  useEffect(() => {
    if (toolNavItems.some((item) => item.to === location.pathname)) {
      setToolsExpanded(true);
    }
  }, [location.pathname]);

  useEffect(() => {
    return () => {
      if (themeAnimationTimerRef.current !== null) {
        window.clearTimeout(themeAnimationTimerRef.current);
      }
      document.documentElement.classList.remove("theme-animating");
    };
  }, []);

  const toggleCollapsed = () => {
    setCollapsed((current) => {
      localStorage.setItem(COLLAPSE_STORAGE_KEY, current ? "0" : "1");
      return !current;
    });
  };

  const toggleTheme = () => {
    setIsDark((current) => {
      const next = !current;
      // 临时挂载过渡类，让深浅切换的颜色变化在 200ms 内平滑完成
      if (themeAnimationTimerRef.current !== null) {
        window.clearTimeout(themeAnimationTimerRef.current);
      }
      document.documentElement.classList.add("theme-animating");
      document.documentElement.classList.toggle("dark", next);
      localStorage.setItem(THEME_STORAGE_KEY, next ? "dark" : "light");
      themeAnimationTimerRef.current = window.setTimeout(() => {
        document.documentElement.classList.remove("theme-animating");
        themeAnimationTimerRef.current = null;
      }, 260);
      return next;
    });
  };

  return (
    <div className="flex min-h-screen">
      <aside
        className={cn(
          "sticky top-0 flex h-screen shrink-0 flex-col border-r border-border/70 bg-card/60 backdrop-blur-md transition-[background-color,border-color,color,transform,width,padding] duration-200",
          collapsed ? "w-14 p-2" : "w-52 p-3",
        )}
      >
        <Link
          to="/"
          className={cn(
            "mb-5 flex items-center gap-2.5 rounded-lg px-1 py-1",
            collapsed && "justify-center",
          )}
          title="Rock PVP Helper"
        >
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-primary to-indigo-500 text-sm font-bold text-primary-foreground shadow-glow-sm">
            R
          </span>
          {!collapsed ? (
            <span className="min-w-0">
              <span className="block truncate text-sm font-semibold tracking-wide">
                Rock PVP Helper
              </span>
              <span className="block truncate text-[10px] text-muted-foreground">
                洛克王国战斗推算
              </span>
            </span>
          ) : null}
        </Link>

        <nav className="flex-1 space-y-0.5">
          {[...primaryNavItems].map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                title={collapsed ? item.label : undefined}
                className={({ isActive }) =>
                  cn(
                    "group relative flex items-center gap-2.5 rounded-lg py-2 text-[13px] font-medium transition-colors",
                    collapsed ? "justify-center px-0" : "px-2.5",
                    isActive
                      ? "bg-primary/10 text-primary"
                      : "text-muted-foreground hover:bg-raised hover:text-foreground",
                  )
                }
              >
                {({ isActive }) => (
                  <>
                    {isActive ? (
                      <span className="absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-full bg-primary shadow-glow-sm" />
                    ) : null}
                    <Icon className="h-4 w-4 shrink-0" />
                    {collapsed ? <span className="sr-only">{item.label}</span> : item.label}
                  </>
                )}
              </NavLink>
            );
          })}

          <div className="pt-1">
            <button
              type="button"
              onClick={() => setToolsExpanded((current) => !current)}
              title={collapsed ? "工具包" : undefined}
              className={cn(
                "group relative flex w-full items-center gap-2.5 rounded-lg py-2 text-[13px] font-medium transition-colors",
                collapsed ? "justify-center px-0" : "px-2.5",
                toolNavItems.some((item) => item.to === location.pathname)
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-raised hover:text-foreground",
              )}
            >
              {toolNavItems.some((item) => item.to === location.pathname) ? (
                <span className="absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-full bg-primary shadow-glow-sm" />
              ) : null}
              <Calculator className="h-4 w-4 shrink-0" />
              {collapsed ? <span className="sr-only">工具包</span> : <span className="flex-1 text-left">工具包</span>}
              {!collapsed ? (
                <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", toolsExpanded && "rotate-180")} />
              ) : null}
            </button>
            {toolsExpanded ? (
              <div className={cn("mt-1 space-y-0.5", collapsed ? "pl-0" : "pl-3")}>
                {toolNavItems.map((item) => {
                  const Icon = item.icon;
                  return (
                    <NavLink
                      key={item.to}
                      to={item.to}
                      title={collapsed ? item.label : undefined}
                      className={({ isActive }) =>
                        cn(
                          "group relative flex items-center gap-2 rounded-lg py-1.5 text-xs font-medium transition-colors",
                          collapsed ? "justify-center px-0" : "px-2.5",
                          isActive
                            ? "bg-primary/10 text-primary"
                            : "text-muted-foreground hover:bg-raised hover:text-foreground",
                        )
                      }
                    >
                      <Icon className="h-3.5 w-3.5 shrink-0" />
                      {collapsed ? <span className="sr-only">{item.label}</span> : item.label}
                    </NavLink>
                  );
                })}
              </div>
            ) : null}
          </div>

          {secondaryNavItems.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                title={collapsed ? item.label : undefined}
                className={({ isActive }) =>
                  cn(
                    "group relative flex items-center gap-2.5 rounded-lg py-2 text-[13px] font-medium transition-colors",
                    collapsed ? "justify-center px-0" : "px-2.5",
                    isActive
                      ? "bg-primary/10 text-primary"
                      : "text-muted-foreground hover:bg-raised hover:text-foreground",
                  )
                }
              >
                {({ isActive }) => (
                  <>
                    {isActive ? (
                      <span className="absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-full bg-primary shadow-glow-sm" />
                    ) : null}
                    <Icon className="h-4 w-4 shrink-0" />
                    {collapsed ? <span className="sr-only">{item.label}</span> : item.label}
                  </>
                )}
              </NavLink>
            );
          })}
        </nav>

        {!collapsed ? (
          <div className="mb-2 rounded-lg border border-border/60 bg-raised/40 p-2.5 text-[10px] leading-4 text-muted-foreground">
            本地手动输入模式。不会自动识图，不会自动推荐出招。
          </div>
        ) : null}

        <div className={cn("flex gap-1", collapsed ? "flex-col" : "flex-row")}>
          <button
            type="button"
            onClick={toggleTheme}
            title={isDark ? "切换到浅色主题" : "切换到深色主题"}
            className={cn(
              "flex flex-1 items-center gap-2 rounded-lg py-2 text-xs text-muted-foreground transition-colors hover:bg-raised hover:text-foreground",
              collapsed ? "justify-center px-0" : "px-2.5",
            )}
          >
            {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            {!collapsed ? (isDark ? "浅色模式" : "深色模式") : null}
          </button>
          <button
            type="button"
            onClick={toggleCollapsed}
            title={collapsed ? "展开侧边栏" : "收起侧边栏"}
            className={cn(
              "flex flex-1 items-center gap-2 rounded-lg py-2 text-xs text-muted-foreground transition-colors hover:bg-raised hover:text-foreground",
              collapsed ? "justify-center px-0" : "px-2.5",
            )}
          >
            {collapsed ? <ChevronsRight className="h-4 w-4" /> : <ChevronsLeft className="h-4 w-4" />}
            {!collapsed ? "收起导航" : null}
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <BattleHud />
        <main className="min-w-0 flex-1 p-6">
          <FormulaUnavailableBanner />
          <div key={location.pathname} className="animate-page-in">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}

/** 顶栏战斗状态 HUD：有当前战斗时展示战斗名、回合数与阶段，并在战斗中轮询最新状态。 */
function BattleHud() {
  const { currentBattleId } = useAppStore();
  const battleQuery = useQuery({
    queryKey: ["battle", currentBattleId],
    queryFn: () => api.battles.get(currentBattleId!),
    enabled: Boolean(currentBattleId),
    retry: false,
  });
  const phase = battleQuery.data?.phase;
  const stateQuery = useQuery({
    queryKey: ["battle-state", currentBattleId],
    queryFn: () => api.battles.state(currentBattleId!),
    enabled: Boolean(currentBattleId) && phase === "battle",
    refetchInterval: 15_000,
    retry: false,
  });

  const battleName =
    battleQuery.data?.battle_name ??
    (currentBattleId ? compactId(currentBattleId) : null);
  const turnNumber = stateQuery.data?.battle.turn_number;

  return (
    <header className="sticky top-0 z-40 flex h-12 items-center justify-between gap-4 border-b border-border/70 bg-background/70 px-6 backdrop-blur-md transition-colors duration-150">
      <div className="flex min-w-0 items-center gap-3 text-sm">
        {currentBattleId ? (
          <>
            <span className="flex min-w-0 items-center gap-2">
              <span
                className={cn(
                  "h-1.5 w-1.5 shrink-0 rounded-full",
                  phase === "battle" ? "bg-success shadow-glow-sm" : "bg-muted-foreground",
                )}
              />
              <span className="truncate font-medium text-foreground">{battleName}</span>
            </span>
            <span className="hidden shrink-0 text-xs text-muted-foreground sm:inline">
              {phaseName(phase)}
            </span>
            {turnNumber !== undefined ? (
              <span className="flex shrink-0 items-baseline gap-1 text-xs text-muted-foreground">
                回合
                <span className="font-num text-base font-semibold text-primary">
                  {turnNumber}
                </span>
              </span>
            ) : null}
          </>
        ) : (
          <span className="text-xs text-muted-foreground">
            未选择战斗 — 从首页创建或进入一场战斗
          </span>
        )}
      </div>
      {currentBattleId ? (
        <Link
          to="/battle"
          className="flex shrink-0 items-center gap-1.5 rounded-md border border-primary/30 bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary transition-colors hover:bg-primary/20"
        >
          <Sword className="h-3.5 w-3.5" />
          进入工作台
        </Link>
      ) : null}
    </header>
  );
}
