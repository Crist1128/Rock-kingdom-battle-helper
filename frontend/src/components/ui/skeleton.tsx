import { cn } from "@/lib/utils";

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-skeleton-shimmer rounded-lg bg-raised/70", className)} />;
}

/** 路由级懒加载的页面占位：标题 + 两张卡片轮廓。 */
export function PageLoadingSkeleton() {
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Skeleton className="h-7 w-40" />
        <Skeleton className="h-4 w-72" />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Skeleton className="h-56" />
        <Skeleton className="h-56" />
      </div>
      <Skeleton className="h-32" />
    </div>
  );
}
