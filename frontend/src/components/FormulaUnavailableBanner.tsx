import { AlertTriangle } from "lucide-react";
import { Badge } from "@/components/ui/badge";

export function FormulaUnavailableBanner() {
  return (
    <div className="mb-5 flex items-center justify-between rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
      <div className="flex items-center gap-3">
        <AlertTriangle className="h-4 w-4" />
        <span>真实伤害公式、真实速度先手概率、图像识别尚未实现。前端只记录事实与展示后端候选占位结果。</span>
      </div>
      <div className="flex gap-2">
        <Badge variant="warning">formula_unavailable</Badge>
        <Badge variant="outline">manual only</Badge>
      </div>
    </div>
  );
}
