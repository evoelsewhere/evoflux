import type * as React from "react";

/**
 * evo tool icons. One 24px grid, 1.5 stroke, round joins, duotone: the
 * outline in `currentColor` over a 12% fill of the same colour, so they stay
 * achromatic (DESIGN.md) and follow light/dark automatically.
 */
type IconProps = React.SVGProps<SVGSVGElement>;

const FILL = { fill: "currentColor", fillOpacity: 0.12 } as const;

function Base({ children, ...props }: IconProps) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      width={24}
      height={24}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      {children}
    </svg>
  );
}

export function TerminalIcon(props: IconProps) {
  return (
    <Base {...props}>
      <rect x="3" y="4.5" width="18" height="15" rx="3" {...FILL} />
      <path d="m7.5 9.5 3 2.5-3 2.5" />
      <path d="M12.5 15h4" />
    </Base>
  );
}

export function BrowserIcon(props: IconProps) {
  return (
    <Base {...props}>
      <rect x="3" y="4.5" width="18" height="15" rx="3" {...FILL} />
      <path d="M3 9h18" />
      <circle cx="6" cy="6.75" r="0.6" fill="currentColor" stroke="none" />
      <circle cx="8.25" cy="6.75" r="0.6" fill="currentColor" stroke="none" />
      <path d="M10.5 12.5h6.5M7 15.5h7" />
    </Base>
  );
}

export function FilesIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path
        d="M3 8a2.5 2.5 0 0 1 2.5-2.5h3.2c.53 0 1.04.21 1.41.59L11.5 7.5h7A2.5 2.5 0 0 1 21 10v6.5a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 16.5Z"
        {...FILL}
      />
      <path d="M3 10.5h18" />
    </Base>
  );
}

export function SideChatIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path
        d="M4 7a2.5 2.5 0 0 1 2.5-2.5h7A2.5 2.5 0 0 1 16 7v3.5a2.5 2.5 0 0 1-2.5 2.5H9.5L6.5 15.5V13A2.5 2.5 0 0 1 4 10.5Z"
        {...FILL}
      />
      <path d="M16 9h2.5A1.5 1.5 0 0 1 20 10.5v4.5a1.5 1.5 0 0 1-1.5 1.5H18V19l-3-2.5h-2.5A1.5 1.5 0 0 1 11 15v-2" />
    </Base>
  );
}

export function MemoryIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M7.5 4.5h9" />
      <rect x="4.5" y="7" width="15" height="13" rx="2.5" {...FILL} />
      <path
        d="m12 10.25.85 1.9 1.9.85-1.9.85-.85 1.9-.85-1.9-1.9-.85 1.9-.85Z"
        fill="currentColor"
        strokeWidth={1}
      />
    </Base>
  );
}

/**
 * The chat summary: the thread (lines at the left and bottom) with the summary
 * card in its top right corner, where the card shows. `open` fills the card.
 */
export function SummaryIcon({ open = false, ...props }: IconProps & { open?: boolean }) {
  return (
    <Base {...props}>
      <rect x="3" y="4.5" width="18" height="15" rx="3" {...FILL} />
      <rect x="12" y="7.5" width="6" height="5.5" rx="1.25" fill={open ? "currentColor" : "none"} />
      <path d="M6.5 9h2.5M6.5 12h2.5M6.5 16h11" />
    </Base>
  );
}

/** The side panel toggle: the window with its right pane, filled while open. */
export function SidePanelIcon({ open = false, ...props }: IconProps & { open?: boolean }) {
  return (
    <Base {...props}>
      <rect x="3" y="4.5" width="18" height="15" rx="3" {...FILL} />
      <path d="M15 4.5h3a3 3 0 0 1 3 3v9a3 3 0 0 1-3 3h-3Z" fill={open ? "currentColor" : "none"} />
      <path d="M6.5 9h4.5M6.5 12h3" />
    </Base>
  );
}

/** Usage: spend per day, as bars. */
export function UsageIcon(props: IconProps) {
  return (
    <Base {...props}>
      <rect x="3.5" y="12" width="4" height="8" rx="1.5" {...FILL} />
      <rect x="10" y="7.5" width="4" height="12.5" rx="1.5" {...FILL} />
      <rect x="16.5" y="4" width="4" height="16" rx="1.5" {...FILL} />
    </Base>
  );
}

export function SchedulerIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M17.5 11.5V8a2.5 2.5 0 0 0-2.5-2.5H6A2.5 2.5 0 0 0 3.5 8v9A2.5 2.5 0 0 0 6 19.5h5" {...FILL} />
      <path d="M7.5 3.5v4M13.5 3.5v4M3.5 10h14" />
      <circle cx="17" cy="17" r="4" />
      <path d="M17 15.25V17l1.25.9" />
    </Base>
  );
}

export function PluginsIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path
        d="M9.5 5a2.25 2.25 0 0 1 4.5 0v1h2.5A1.5 1.5 0 0 1 18 7.5V10h1a2.25 2.25 0 0 1 0 4.5h-1v2.5a1.5 1.5 0 0 1-1.5 1.5H14v-1a2.25 2.25 0 0 0-4.5 0v1H7a1.5 1.5 0 0 1-1.5-1.5v-2.5h1a2.25 2.25 0 0 0 0-4.5h-1V7.5A1.5 1.5 0 0 1 7 6h2.5Z"
        {...FILL}
      />
    </Base>
  );
}
