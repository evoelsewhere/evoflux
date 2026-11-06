import { MessageScrollerProvider } from "@/components/ui/message-scroller";
import { ApprovalPanel, usePendingPermission } from "./approval-panel";
import { ChatComposer } from "./chat-composer";
import { ChatThread } from "./chat-thread";
import { QuestionsPanel } from "./questions-panel";
import { TodoBar } from "./todo-bar";
import { EngineBanner } from "./engine-banner";

/** The main column: thread above, composer pinned below. */
export function ChatView() {
  const permission = usePendingPermission();
  return (
    <MessageScrollerProvider autoScroll>
      <div className="@container flex h-full min-h-0 min-w-0 flex-col overflow-hidden">
        <div className="min-h-0 flex-1">
          <ChatThread />
        </div>
        <div className="mx-auto w-full max-w-(--chat-width) px-6 pb-5">
          <EngineBanner />
          {/* A permission request takes the composer's place until it is answered. */}
          {/* (The composer stays mounted so a draft survives the prompt.) */}
          <TodoBar />
          {permission?.kind === "questions" ? (
            <QuestionsPanel key={permission.requestId} permission={permission} />
          ) : (
            permission && <ApprovalPanel permission={permission} />
          )}
          <div hidden={Boolean(permission)}>
            <ChatComposer />
          </div>
        </div>
      </div>
    </MessageScrollerProvider>
  );
}
