import * as React from "react";
import {
  MessageScroller,
  MessageScrollerButton,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerViewport,
} from "@/components/ui/message-scroller";
import { Button } from "@/components/ui/button";
import { useEngineStore, useRestoring } from "@/stores/engine-store";
import { useSessionStore } from "@/stores/session-store";
import { ChatSkeleton } from "./chat-skeleton";
import { AssistantMessage, UserMessage } from "./chat-turn";
import { ChatEmpty } from "./chat-empty";
import type { Turn } from "./transcript";

/**
 * One turn of the thread. A delta replaces only the running turn's object, so
 * every earlier turn skips rendering while a reply streams.
 */
const ThreadTurn = React.memo(function ThreadTurn({ turn }: { turn: Turn }) {
  return (
    <div className="flex flex-col gap-6">
      <MessageScrollerItem messageId={`${turn.id}-prompt`} scrollAnchor>
        <UserMessage turn={turn} />
      </MessageScrollerItem>
      <MessageScrollerItem messageId={`${turn.id}-reply`}>
        <AssistantMessage turn={turn} />
      </MessageScrollerItem>
    </div>
  );
});

/** The thread (shadcn/ui AI Elements · Chat): the person's turn anchors the scroll. */
export function ChatThread() {
  const turns = useEngineStore((s) => s.transcript.turns);
  const busy = useEngineStore((s) => s.transcript.busy);
  const restoring = useRestoring();
  // A chat was clicked and is on its way (the sidebar shows it, the thread not yet).
  const activeId = useEngineStore((s) => s.activeId);
  const switching = useSessionStore((s) => {
    if (!s.currentId || s.currentId === activeId) return false;
    const target = s.sessions.find((chat) => chat.id === s.currentId) ?? s.archived.find((chat) => chat.id === s.currentId);
    return Boolean(target && !target.draft);
  });
  // A saved chat that could not be loaded (the engine is up but said no).
  const failed = useEngineStore((s) => (s.status === "ready" ? s.error : undefined));

  // A saved chat is loading: its shape, not the previous chat or the empty "new chat" screen.
  if (switching || (restoring && turns.length === 0)) return <ChatSkeleton />;

  if (turns.length === 0) {
    if (failed) {
      return (
        <div className="grid h-full place-items-center px-6">
          <div className="flex max-w-md flex-col items-center gap-3 text-center">
            <p className="text-sm text-muted-foreground" data-selectable>
              {failed}
            </p>
            <Button size="sm" variant="outline" onClick={() => void useEngineStore.getState().start()}>
              Try again
            </Button>
          </div>
        </div>
      );
    }
    return <ChatEmpty />;
  }

  return (
    <MessageScroller>
      <MessageScrollerViewport>
        <MessageScrollerContent aria-busy={busy} className="mx-auto w-full max-w-(--chat-width) gap-8 px-6 py-6">
          {turns.map((turn) => (
            <ThreadTurn key={turn.id} turn={turn} />
          ))}
        </MessageScrollerContent>
      </MessageScrollerViewport>
      <MessageScrollerButton />
    </MessageScroller>
  );
}
