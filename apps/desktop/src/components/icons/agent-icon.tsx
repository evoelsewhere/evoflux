import * as React from "react";
import { cn } from "@/lib/utils";

// evo's agents: a solid body with two capsule eyes cut out of it, so the eyes
// show whatever is behind (light or dark theme alike). One family, a look per
// agent type; while an agent runs its eyes blink now and then.

type Look = "general" | "explore" | "plan" | "background";

const looks: Record<Look, { body: React.ReactNode; eyes: React.ReactNode }> = {
  // A ball glancing up and to the right.
  general: {
    body: <circle cx="12" cy="13" r="10.5" />,
    eyes: (
      <>
        <rect x="12.9" y="5.6" width="2.6" height="5.4" rx="1.3" transform="rotate(-24 14.2 8.3)" />
        <rect x="16.9" y="5.4" width="2.3" height="4.6" rx="1.15" transform="rotate(-24 18.05 7.7)" />
      </>
    ),
  },
  // Eyes to the side: looking for something.
  explore: {
    body: <circle cx="12" cy="13" r="10.5" />,
    eyes: (
      <>
        <rect x="15.2" y="9" width="2.6" height="5.2" rx="1.3" transform="rotate(-8 16.5 11.6)" />
        <rect x="19" y="9.2" width="2.2" height="4.4" rx="1.1" transform="rotate(-8 20.1 11.4)" />
      </>
    ),
  },
  // Square and steady, looking straight at you.
  plan: {
    body: <rect x="2" y="3" width="20" height="20" rx="7" />,
    eyes: (
      <>
        <rect x="8.2" y="8.4" width="2.6" height="5.4" rx="1.3" />
        <rect x="13.2" y="8.4" width="2.6" height="5.4" rx="1.3" />
      </>
    ),
  },
  // Calm, half-closed eyes: works while you are away.
  background: {
    body: <circle cx="12" cy="13" r="10.5" />,
    eyes: (
      <>
        <rect x="12.4" y="9" width="4.2" height="2.2" rx="1.1" transform="rotate(-12 14.5 10.1)" />
        <rect x="17.4" y="8.2" width="3.6" height="2" rx="1" transform="rotate(-12 19.2 9.2)" />
      </>
    ),
  },
};

const lookOf = (agentType?: string, background?: boolean): Look =>
  background ? "background" : agentType === "explore" || agentType === "plan" ? agentType : "general";

export function AgentIcon({
  agentType,
  background,
  live,
  className,
  ...props
}: React.SVGProps<SVGSVGElement> & {
  /** `explore`, `plan`; anything else (or a custom type) is the plain ball. */
  agentType?: string;
  /** A background agent's calm look. */
  background?: boolean;
  /** Running: the eyes blink now and then. */
  live?: boolean;
}) {
  const id = `agent-eyes-${React.useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const look = looks[lookOf(agentType, background)];
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      width="24"
      height="24"
      fill="currentColor"
      aria-hidden="true"
      className={cn("shrink-0", className)}
      {...props}
    >
      <defs>
        <mask id={id}>
          <rect width="24" height="24" fill="white" />
          <g
            fill="black"
            className={cn(
              "origin-center [transform-box:fill-box]",
              live && "motion-safe:animate-[agent-blink_3.6s_ease-in-out_infinite]",
            )}
          >
            {look.eyes}
          </g>
        </mask>
      </defs>
      <g mask={`url(#${id})`}>{look.body}</g>
    </svg>
  );
}
