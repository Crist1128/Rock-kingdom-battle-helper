import * as React from "react";
import { cn } from "@/lib/utils";

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "flex h-10 w-full rounded-lg border border-input bg-raised/60 px-3 py-2 text-sm text-foreground outline-none transition-colors",
        "placeholder:text-muted-foreground/70 hover:border-muted-foreground/40",
        "focus:border-primary/60 focus:ring-2 focus:ring-ring/30",
        "disabled:cursor-not-allowed disabled:opacity-40",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...props }, ref) => (
    <textarea
      ref={ref}
      className={cn(
        "min-h-24 w-full rounded-lg border border-input bg-raised/60 px-3 py-2 text-sm text-foreground outline-none transition-colors",
        "placeholder:text-muted-foreground/70 hover:border-muted-foreground/40",
        "focus:border-primary/60 focus:ring-2 focus:ring-ring/30",
        "disabled:cursor-not-allowed disabled:opacity-40",
        className,
      )}
      {...props}
    />
  ),
);
Textarea.displayName = "Textarea";
