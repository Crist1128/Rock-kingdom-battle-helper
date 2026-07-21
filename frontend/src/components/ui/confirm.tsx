import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export interface ConfirmOptions {
  title: string;
  description?: string;
  confirmText?: string;
  cancelText?: string;
  danger?: boolean;
}

type ConfirmFn = (options: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<ConfirmFn | null>(null);

export function useConfirm(): ConfirmFn {
  const context = useContext(ConfirmContext);
  if (!context) throw new Error("useConfirm 必须在 ConfirmProvider 内使用");
  return context;
}

interface PendingConfirm {
  options: ConfirmOptions;
  resolve: (value: boolean) => void;
}

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<PendingConfirm | null>(null);

  const confirm = useCallback<ConfirmFn>(
    (options) =>
      new Promise<boolean>((resolve) => {
        setPending({ options, resolve });
      }),
    [],
  );

  const close = useCallback(
    (value: boolean) => {
      pending?.resolve(value);
      setPending(null);
    },
    [pending],
  );

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {pending ? (
        <div className="fixed inset-0 z-[90] flex items-center justify-center p-4">
          <button
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={() => close(false)}
            aria-label="取消"
          />
          <div
            role="alertdialog"
            aria-modal="true"
            aria-label={pending.options.title}
            className={cn(
              "relative w-full max-w-sm rounded-xl border bg-card p-5 shadow-2xl",
              "animate-[toast-in_160ms_ease-out]",
              pending.options.danger && "border-destructive/30",
            )}
          >
            <h3 className="text-sm font-semibold tracking-wide">{pending.options.title}</h3>
            {pending.options.description ? (
              <p className="mt-2 whitespace-pre-line text-xs leading-5 text-muted-foreground">
                {pending.options.description}
              </p>
            ) : null}
            <div className="mt-5 flex justify-end gap-2">
              <Button variant="outline" size="sm" onClick={() => close(false)}>
                {pending.options.cancelText ?? "取消"}
              </Button>
              <Button
                variant={pending.options.danger ? "destructive" : "default"}
                size="sm"
                onClick={() => close(true)}
                autoFocus
              >
                {pending.options.confirmText ?? "确认"}
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </ConfirmContext.Provider>
  );
}
