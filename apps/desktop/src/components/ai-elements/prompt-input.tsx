import * as React from "react";
import { ArrowUpIcon, FileIcon, FileTextIcon, SquareIcon, XIcon } from "lucide-react";
import {
  Attachment,
  AttachmentAction,
  AttachmentActions,
  AttachmentContent,
  AttachmentMedia,
  AttachmentTitle,
} from "@/components/ui/attachment";
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupTextarea } from "@/components/ui/input-group";
import { cn } from "@/lib/utils";

export interface PromptAttachment {
  /** A file's path, or a made-up key for pasted content. */
  id: string;
  name: string;
  /** `file` (default): sent as an `@path` reference. */
  kind?: "file" | "image" | "text";
  /** A file on disk (a file, or a pasted one saved to the cache). */
  path?: string;
  /** image: the picture, encoded to fit when sent. */
  blob?: Blob;
  /** image: a thumbnail URL. */
  preview?: string;
  /** text: pasted text kept out of the field. */
  text?: string;
}

function AttachmentIcon({ file }: { file: PromptAttachment }) {
  if (file.kind === "image" && file.preview) return <img src={file.preview} alt="" />;
  return file.kind === "text" ? <FileTextIcon /> : <FileIcon />;
}

/** A leading `/command` shown as a token, with its argument hint after it. */
export interface PromptHighlight {
  /** The token's length at the start of the text (`/name`). */
  length: number;
  /** Shown faintly after the token while no arguments are typed. */
  hint?: string | null;
}

/**
 * A message field with attachments and a send button (AI Elements · Prompt
 * Input). `toolbar` fills the bottom row between the leading actions and send.
 * `popover` floats above the field (the `/` menu); `onKeyDownCapture` sees keys
 * first and returns true when it handled one. `highlight` marks a leading
 * command: a layer behind the transparent textarea paints the token.
 *
 * While `busy`, Enter still sends (`onSubmit(false)`: the agent reads it at its
 * next step) and Ctrl/⌘+Enter queues it for after the run (`onSubmit(true)`).
 * `header` sits above the field (messages waiting to be delivered).
 */
export function PromptInput({
  value,
  onChange,
  onSubmit,
  onStop,
  busy,
  disabled,
  placeholder,
  attachments = [],
  onRemoveAttachment,
  leading,
  toolbar,
  popover,
  highlight,
  onKeyDownCapture,
  textareaRef,
  onPaste,
  header,
  dropActive,
}: {
  value: string;
  onChange(value: string): void;
  onSubmit(queue: boolean): void;
  onStop?(): void;
  busy?: boolean;
  disabled?: boolean;
  placeholder?: string;
  attachments?: PromptAttachment[];
  onRemoveAttachment?(id: string): void;
  leading?: React.ReactNode;
  toolbar?: React.ReactNode;
  popover?: React.ReactNode;
  highlight?: PromptHighlight | null;
  onKeyDownCapture?(event: React.KeyboardEvent<HTMLTextAreaElement>): boolean;
  textareaRef?: React.RefObject<HTMLTextAreaElement | null>;
  onPaste?(event: React.ClipboardEvent<HTMLTextAreaElement>): void;
  header?: React.ReactNode;
  /** Files are being dragged over the window. */
  dropActive?: boolean;
}) {
  const formRef = React.useRef<HTMLFormElement>(null);
  const backdropRef = React.useRef<HTMLDivElement>(null);
  const token = highlight ? value.slice(0, highlight.length) : "";
  const rest = highlight ? value.slice(highlight.length) : "";
  const showHint = !!highlight?.hint && rest.trim() === "";
  const canSend = !disabled && (value.trim().length > 0 || attachments.length > 0);
  const queueNext = React.useRef(false);

  return (
    <form
      ref={formRef}
      className="relative"
      onSubmit={(event) => {
        event.preventDefault();
        const queue = queueNext.current;
        queueNext.current = false;
        if (canSend) onSubmit(queue);
      }}
    >
      {header}
      <InputGroup
        className={cn(
          "bg-card shadow-border-medium dark:bg-card",
          dropActive && "border-brand/60 ring-3 ring-brand/15",
        )}
      >
        {attachments.length > 0 && (
          <InputGroupAddon align="block-start" className="flex-wrap">
            {attachments.map((file) => (
              <Attachment key={file.id} size="sm" title={file.path ?? file.name}>
                <AttachmentMedia variant={file.kind === "image" && file.preview ? "image" : "icon"}>
                  <AttachmentIcon file={file} />
                </AttachmentMedia>
                <AttachmentContent>
                  <AttachmentTitle>{file.name}</AttachmentTitle>
                </AttachmentContent>
                {onRemoveAttachment && (
                  <AttachmentActions>
                    <AttachmentAction aria-label={`Remove ${file.name}`} onClick={() => onRemoveAttachment(file.id)}>
                      <XIcon />
                    </AttachmentAction>
                  </AttachmentActions>
                )}
              </Attachment>
            ))}
          </InputGroupAddon>
        )}
        <div className="relative w-full min-w-0">
          {highlight && (
            // Same box and type as the textarea, so the token sits under its text.
            <div
              ref={backdropRef}
              aria-hidden
              className="pointer-events-none absolute inset-0 overflow-hidden p-3 text-base break-words whitespace-pre-wrap text-transparent md:text-sm"
            >
              <span className="rounded-[4px] bg-brand/14 ring-2 ring-brand/14">{token}</span>
              {rest}
              {showHint && <span className="text-muted-foreground/70">{rest.length ? "" : " "}{highlight.hint}</span>}
            </div>
          )}
          <InputGroupTextarea
            ref={textareaRef}
            value={value}
            onChange={(event) => onChange(event.target.value)}
            onPaste={onPaste}
            onScroll={(event) => {
              if (backdropRef.current) backdropRef.current.scrollTop = event.currentTarget.scrollTop;
            }}
            placeholder={placeholder}
            aria-label="Message"
            disabled={disabled}
            className="relative max-h-60 min-h-14 p-3"
            onKeyDown={(event) => {
              if (onKeyDownCapture?.(event)) return;
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                queueNext.current = busy === true && (event.ctrlKey || event.metaKey);
                formRef.current?.requestSubmit();
              }
            }}
          />
        </div>
        <InputGroupAddon align="block-end" className="gap-1">
          {leading}
          <div className="ml-auto flex min-w-0 items-center gap-1">{toolbar}</div>
          {busy && onStop && (
            <InputGroupButton
              type="button"
              size="icon-sm"
              variant={canSend ? "secondary" : "default"}
              aria-label="Stop"
              title="Stop"
              onClick={onStop}
            >
              <SquareIcon className="fill-current" />
            </InputGroupButton>
          )}
          {(!busy || canSend) && (
            <InputGroupButton
              type="submit"
              size="icon-sm"
              variant="default"
              aria-label={busy ? "Send now" : "Send"}
              title={busy ? "Send now (Enter) · queue for later (Ctrl+Enter)" : "Send"}
              disabled={!canSend}
            >
              <ArrowUpIcon />
            </InputGroupButton>
          )}
        </InputGroupAddon>
      </InputGroup>
      {popover && <div className="absolute inset-x-0 bottom-full z-30 mb-2">{popover}</div>}
    </form>
  );
}
