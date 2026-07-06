import { AlertTriangle } from "lucide-react";
import { Badge } from "@/components/ui/badge";

export function FormulaUnavailableBanner() {
  return (
    <div className="mb-5 flex items-center justify-between rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
      <div className="flex items-center gap-3">
        <AlertTriangle className="h-4 w-4" />
        <span>普通攻击、状态伤害、星陨和应对/防御减伤已可测试；真实速度概率、图像识别和完整公式分支仍未完成，实时估计会优先记录 unknown factors。</span>
      </div>
      <div className="flex gap-2">
        <Badge variant="success">estimate</Badge>
        <Badge variant="outline">unknown first</Badge>
      </div>
    </div>
  );
}
