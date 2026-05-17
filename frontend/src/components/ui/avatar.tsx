import { useState } from "react";
import { cn } from "@/lib/utils";

export function AvatarImage({
  src,
  alt,
  fallback,
  className,
}: {
  src?: string | null;
  alt?: string;
  fallback?: string;
  className?: string;
}) {
  const [failed, setFailed] = useState(false);
  const text = (fallback || alt || "?").trim().slice(0, 2) || "?";

  if (src && !failed) {
    return (
      <img
        src={src}
        alt={alt ?? text}
        loading="lazy"
        decoding="async"
        referrerPolicy="no-referrer"
        className={cn("h-10 w-10 rounded-xl object-cover bg-muted", className)}
        onError={() => setFailed(true)}
      />
    );
  }

  return (
    <div className={cn("flex h-10 w-10 items-center justify-center rounded-xl bg-muted text-xs font-semibold", className)}>
      {text}
    </div>
  );
}
