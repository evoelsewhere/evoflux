import * as React from "react";
import { Input } from "@/components/ui/input";

type Hsv = { h: number; s: number; v: number };

function hexToHsv(hex: string): Hsv {
  const n = parseInt(hex.slice(1), 16);
  const r = ((n >> 16) & 255) / 255, g = ((n >> 8) & 255) / 255, b = (n & 255) / 255;
  const max = Math.max(r, g, b), d = max - Math.min(r, g, b);
  let h = 0;
  if (d) h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return { h: (h * 60 + 360) % 360, s: max ? d / max : 0, v: max };
}

function hsvToHex({ h, s, v }: Hsv): string {
  const f = (n: number) => {
    const k = (n + h / 60) % 6;
    return Math.round((v - v * s * Math.max(0, Math.min(k, 4 - k, 1))) * 255);
  };
  return "#" + [f(5), f(3), f(1)].map((x) => x.toString(16).padStart(2, "0")).join("");
}

/** Drag area reporting 0–1 positions. */
function Area({ onMove, className, style, children, label }: { onMove(x: number, y: number): void; className: string; style?: React.CSSProperties; children: React.ReactNode; label: string }) {
  const report = (e: React.PointerEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    onMove(Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)));
  };
  return (
    <div
      role="presentation"
      aria-label={label}
      className={`relative touch-none select-none ${className}`}
      style={style}
      onPointerDown={(e) => {
        e.currentTarget.setPointerCapture(e.pointerId);
        report(e);
      }}
      onPointerMove={(e) => e.buttons === 1 && report(e)}
    >
      {children}
    </div>
  );
}

const thumb = "pointer-events-none absolute size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white shadow-[0_0_0_1px_rgb(0_0_0/0.4)]";

/** Saturation/value square, hue strip and a hex field. */
export function ColorPicker({ value, onChange }: { value: string; onChange(hex: string): void }) {
  const [hsv, setHsv] = React.useState(() => hexToHsv(value));
  const [text, setText] = React.useState(value);
  const last = React.useRef(value);
  React.useEffect(() => {
    if (value !== last.current) {
      last.current = value;
      setHsv(hexToHsv(value));
      setText(value);
    }
  }, [value]);
  const apply = (next: Hsv) => {
    setHsv(next);
    const hex = hsvToHex(next);
    last.current = hex;
    setText(hex);
    onChange(hex);
  };
  return (
    <div className="flex w-52 flex-col gap-3">
      <Area
        label="Saturation and brightness"
        className="h-32 cursor-crosshair rounded-lg"
        style={{ background: `linear-gradient(to top,#000,transparent),linear-gradient(to right,#fff,hsl(${hsv.h} 100% 50%))` }}
        onMove={(x, y) => apply({ ...hsv, s: x, v: 1 - y })}
      >
        <span className={thumb} style={{ left: `${hsv.s * 100}%`, top: `${(1 - hsv.v) * 100}%` }} />
      </Area>
      <Area
        label="Hue"
        className="h-3 cursor-pointer rounded-full"
        style={{ background: "linear-gradient(to right,#f00,#ff0,#0f0,#0ff,#00f,#f0f,#f00)" }}
        onMove={(x) => apply({ ...hsv, h: x * 360 })}
      >
        <span className={thumb} style={{ left: `${(hsv.h / 360) * 100}%`, top: "50%" }} />
      </Area>
      <Input
        aria-label="Hex colour"
        value={text}
        maxLength={7}
        spellCheck={false}
        className="h-8 rounded-lg font-mono text-xs"
        onChange={(e) => {
          const t = e.target.value.startsWith("#") ? e.target.value : `#${e.target.value}`;
          setText(t);
          if (/^#[0-9a-fA-F]{6}$/.test(t)) {
            last.current = t.toLowerCase();
            setHsv(hexToHsv(t));
            onChange(t.toLowerCase());
          }
        }}
      />
    </div>
  );
}
