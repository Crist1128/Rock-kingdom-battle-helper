import { useEffect, useState } from "react";
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

  useEffect(() => {
    setFailed(false);
  }, [src]);

  if (src && !failed) {
    return (
      <img
        src={src}
        alt={alt ?? text}
        loading="lazy"
        decoding="async"
        referrerPolicy="no-referrer"
        className={cn("h-10 w-10 rounded-lg border border-border/60 bg-raised object-cover", className)}
        onError={() => setFailed(true)}
      />
    );
  }

  return (
    <div
      className={cn(
        "flex h-10 w-10 items-center justify-center rounded-lg border border-border/60 bg-raised text-xs font-semibold text-muted-foreground",
        className,
      )}
    >
      {text}
    </div>
  );
}
