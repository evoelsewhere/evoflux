import * as React from "react";
import { Confirmation } from "@/components/ai-elements/confirmation";
import { Kbd } from "@/components/ui/kbd";
import { StatusDot } from "@/components/status-dot";
import { useEngineStore } from "@/stores/engine-store";
import type { PermissionRequest } from "./transcript";

/** The pending permission request of the running turn, if any. */
export function usePendingPermission(): PermissionRequest | undefined {
  return useEngineStore((s) => s.transcript.turns.at(-1)?.permission);
}

const rejects = (option: { title: string; permission?: string }) =>
  option.permission?.startsWith("reject") || /^(deny|reject|no)\b/i.test(option.title);

/**
 * A permission request takes the composer's place until it is answered, as in
 * DeepSeek Harness: Enter allows once, Esc rejects (shadcn/ui AI Elements ·
 * Confirmation). It sits outside the thread because it is a prompt, not
 * activity.
 */
export function ApprovalPanel({ permission }: { permission: PermissionRequest }) {
  const answerPermission = useEngineStore((s) => s.answerPermission);
  const allowIndex = permission.options.findIndex((option) => !rejects(option));
  const rejectIndex = permission.options.findIndex(rejects);
  const answer = React.useCallback(
    (index: number) => {
      const option = permission.options[index];
      if (option) void answerPermission(permission.requestId, option, index);
    },
    [answerPermission, permission],
  );

  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.isComposing) return;
      if (event.key === "Enter" && allowIndex !== -1) {
        event.preventDefault();
        answer(allowIndex);
      } else if (event.key === "Escape" && rejectIndex !== -1) {
        event.preventDefault();
        answer(rejectIndex);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [answer, allowIndex, rejectIndex]);

  return (
    <div className="flex flex-col gap-2" role="alertdialog" aria-label={permission.title}>
      <div className="flex items-center gap-2 px-1 text-xs text-muted-foreground">
        <StatusDot tone="warn" pulse />
        Waiting for your approval
        <span className="ml-auto flex items-center gap-1.5">
          {allowIndex !== -1 && (
            <>
              <Kbd>Enter</Kbd> {permission.options[allowIndex].title.toLowerCase()}
            </>
          )}
          {rejectIndex !== -1 && (
            <>
              <Kbd className="ml-2">Esc</Kbd> {permission.options[rejectIndex].title.toLowerCase()}
            </>
          )}
        </span>
      </div>
      <Confirmation
        title={permission.title}
        description={permission.description}
        options={permission.options}
        onAnswer={(_, index) => answer(index)}
      />
    </div>
  );
}
