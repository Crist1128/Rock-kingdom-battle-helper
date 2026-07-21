import * as React from "react";
import { cn } from "@/lib/utils";

export function Select({ className, ...props }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        "flex h-10 w-full rounded-lg border border-input bg-raised/60 px-3 py-2 text-sm text-foreground outline-none transition-colors",
        "hover:border-muted-foreground/40 focus:border-primary/60 focus:ring-2 focus:ring-ring/30",
        "disabled:cursor-not-allowed disabled:opacity-40",
        "[color-scheme:dark] [&_option]:bg-card [&_option]:text-foreground",
        className,
      )}
      {...props}
    />
  );
}
