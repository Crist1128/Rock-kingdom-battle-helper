import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        raised: "hsl(var(--raised))",
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        self: {
          DEFAULT: "hsl(var(--self))",
        },
        enemy: {
          DEFAULT: "hsl(var(--enemy))",
        },
        success: "hsl(var(--success))",
        warning: "hsl(var(--warning))",
        info: "hsl(var(--info))",
        accentv: "hsl(var(--accentv))",
        accenti: "hsl(var(--accenti))",
      },
      // 圆角全面收紧：xl 16→10px、2xl 20→12px，去掉圆润感，走锐利科技风
      borderRadius: {
        xl: "0.625rem",
        "2xl": "0.75rem",
      },
      boxShadow: {
        glow: "0 0 24px hsl(var(--primary) / 0.16)",
        "glow-sm": "0 0 12px hsl(var(--primary) / 0.22)",
      },
      transitionDuration: {
        DEFAULT: "150ms",
      },
    },
  },
  plugins: [],
};

export default config;
