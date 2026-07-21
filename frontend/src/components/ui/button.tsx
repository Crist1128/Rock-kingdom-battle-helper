import * as React from "react";
import { cn } from "@/lib/utils";

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "secondary" | "outline" | "ghost" | "destructive";
  size?: "sm" | "md" | "lg";
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", size = "md", ...props }, ref) => {
    const variants = {
      default: "bg-primary text-primary-foreground font-semibold hover:bg-primary/85 hover:shadow-glow-sm",
      secondary: "bg-raised text-foreground hover:bg-muted",
      outline: "border border-input bg-transparent text-foreground hover:border-primary/50 hover:bg-primary/5 hover:text-primary",
      ghost: "text-muted-foreground hover:bg-raised hover:text-foreground",
      destructive: "border border-destructive/30 bg-destructive/12 text-destructive hover:bg-destructive/20",
    };
    const sizes = {
      sm: "h-8 px-3 text-xs",
      md: "h-10 px-4 text-sm",
      lg: "h-11 px-5 text-base",
    };
    return (
      <button
        ref={ref}
        className={cn(
          "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-all duration-150 motion-safe:active:scale-[0.97]",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60",
          "disabled:pointer-events-none disabled:opacity-40",
          variants[variant],
          sizes[size],
          className,
        )}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";
