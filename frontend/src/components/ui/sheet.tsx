import * as React from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "./button";

interface SheetProps {
  open: boolean;
  title: string;
  description?: string;
  onClose: () => void;
  children: React.ReactNode;
  widthClassName?: string;
}

export function Sheet({ open, title, description, onClose, children, widthClassName }: SheetProps) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
        aria-label="关闭抽屉背景"
      />
      <aside
        className={cn(
          "relative h-full w-[520px] overflow-y-auto border-l border-border/80 bg-card/95 shadow-2xl backdrop-blur-md",
          widthClassName,
        )}
      >
        <div className="sticky top-0 z-10 flex items-start justify-between border-b border-border/70 bg-card/90 p-5 backdrop-blur">
          <div>
            <h2 className="text-base font-semibold tracking-wide">{title}</h2>
            {description ? <p className="mt-1 text-xs text-muted-foreground">{description}</p> : null}
          </div>
          <Button variant="ghost" size="sm" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>
        <div className="p-5">{children}</div>
      </aside>
    </div>
  );
}
