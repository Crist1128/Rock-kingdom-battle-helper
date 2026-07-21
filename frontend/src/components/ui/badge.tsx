import * as React from "react";
import { cn } from "@/lib/utils";

export function Badge({
  className,
  variant = "default",
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & { variant?: "default" | "secondary" | "outline" | "destructive" | "warning" | "success" }) {
  const variants = {
    default: "border border-primary/30 bg-primary/12 text-primary",
    secondary: "border border-transparent bg-raised text-muted-foreground",
    outline: "border border-border bg-transparent text-muted-foreground",
    destructive: "border border-destructive/30 bg-destructive/12 text-destructive",
    warning: "border border-warning/30 bg-warning/12 text-warning",
    success: "border border-success/30 bg-success/12 text-success",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-medium tracking-wide",
        variants[variant],
        className,
      )}
      {...props}
    />
  );
}
