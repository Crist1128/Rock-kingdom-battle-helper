import { useState } from "react";
import { AlertTriangle, X } from "lucide-react";

const DISMISS_STORAGE_KEY = "rock-pvp-helper.formulaBannerDismissed";

export function FormulaUnavailableBanner() {
  const [dismissed, setDismissed] = useState(
    () => localStorage.getItem(DISMISS_STORAGE_KEY) === "1",
  );

  if (dismissed) return null;

  const dismiss = () => {
    localStorage.setItem(DISMISS_STORAGE_KEY, "1");
    setDismissed(true);
  };

  return (
    <div className="mb-4 flex items-center gap-3 rounded-lg border border-warning/25 bg-warning/10 px-3 py-2 text-xs text-warning">
      <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
      <span className="min-w-0 flex-1 leading-5">
        普通攻击、状态伤害、星陨和应对/防御减伤已可测试；真实速度概率、图像识别和完整公式分支仍未完成，实时估计会优先记录 unknown factors。
      </span>
      <button
        type="button"
        onClick={dismiss}
        aria-label="关闭提示"
        className="shrink-0 rounded p-0.5 text-warning/70 transition-colors hover:bg-warning/15 hover:text-warning"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
