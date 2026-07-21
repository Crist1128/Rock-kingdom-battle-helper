import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { AlertCircle, CheckCircle2, Info, X } from "lucide-react";
import { cn } from "@/lib/utils";

export type ToastVariant = "default" | "success" | "error";

interface ToastItem {
  id: number;
  message: string;
  variant: ToastVariant;
  closing?: boolean;
}

interface ToastContextValue {
  toast: (message: string, variant?: ToastVariant) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

let nextToastId = 0;

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast 必须在 ToastProvider 内使用");
  return context;
}

const VARIANT_STYLES: Record<ToastVariant, { icon: typeof Info; className: string }> = {
  default: { icon: Info, className: "border-border text-foreground" },
  success: { icon: CheckCircle2, className: "border-success/30 text-foreground [&_svg]:text-success" },
  error: { icon: AlertCircle, className: "border-destructive/30 text-foreground [&_svg]:text-destructive" },
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const timersRef = useRef<number[]>([]);

  const schedule = useCallback((callback: () => void, delay: number) => {
    const timer = window.setTimeout(() => {
      timersRef.current = timersRef.current.filter((item) => item !== timer);
      callback();
    }, delay);
    timersRef.current.push(timer);
    return timer;
  }, []);

  useEffect(() => {
    return () => {
      timersRef.current.forEach((timer) => window.clearTimeout(timer));
      timersRef.current = [];
    };
  }, []);

  const dismiss = useCallback((id: number) => {
    setItems((current) =>
      current.map((item) => (item.id === id ? { ...item, closing: true } : item)),
    );
    schedule(() => {
      setItems((current) => current.filter((item) => item.id !== id));
    }, 170);
  }, [schedule]);

  const toast = useCallback(
    (message: string, variant: ToastVariant = "default") => {
      const id = ++nextToastId;
      setItems((current) => [...current.slice(-3), { id, message, variant }]);
      schedule(() => dismiss(id), 4200);
    },
    [dismiss, schedule],
  );

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div className="pointer-events-none fixed right-4 top-14 z-[100] flex w-80 max-w-[90vw] flex-col gap-2">
        {items.map((item) => {
          const style = VARIANT_STYLES[item.variant];
          const Icon = style.icon;
          return (
            <div
              key={item.id}
              className={cn(
                "pointer-events-auto flex items-start gap-2.5 rounded-lg border bg-card/95 p-3 text-sm shadow-xl backdrop-blur-md transition-colors duration-150",
                item.closing ? "animate-toast-out" : "animate-toast-in",
                style.className,
              )}
              role="status"
            >
              <Icon className="mt-0.5 h-4 w-4 shrink-0" />
              <span className="min-w-0 flex-1 whitespace-pre-line leading-5">{item.message}</span>
              <button
                type="button"
                onClick={() => dismiss(item.id)}
                aria-label="关闭提示"
                className="shrink-0 rounded p-0.5 text-muted-foreground transition-colors hover:bg-raised hover:text-foreground"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}
