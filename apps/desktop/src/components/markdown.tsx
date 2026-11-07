"use client";

import * as React from "react";
import { Streamdown, useIsCodeFenceIncomplete, type ExtraProps } from "streamdown";
import {
  CodeBlock,
  CodeBlockActions,
  CodeBlockContent,
  CodeBlockCopyButton,
  CodeBlockHeader,
  CodeBlockLine,
  CodeBlockTitle,
} from "@/components/ui/code-block";
import { useHighlightedCode } from "@/hooks/use-highlighted-code";
import { useSmoothText } from "@/hooks/use-smooth-text";
import { cn } from "@/lib/utils";

// shadcn/ui · Code Block › Markdown: render the reply with Streamdown and
// route fenced code to a CodeBlock, so code gets line highlighting and a copy
// button. Streamdown sets `data-block` on fenced code only.

function MarkdownCodeBlock({ code, language }: { code: string; language: string }) {
  // True while the closing fence has not arrived yet.
  const incomplete = useIsCodeFenceIncomplete();
  const lines = useHighlightedCode(code, language);

  return (
    <CodeBlock className="my-3">
      <CodeBlockHeader>
        <CodeBlockTitle>{language || "text"}</CodeBlockTitle>
        <CodeBlockActions>
          <CodeBlockCopyButton value={code} disabled={incomplete} />
        </CodeBlockActions>
      </CodeBlockHeader>
      <CodeBlockContent className="max-h-[28rem]" data-selectable>
        {lines.map((line, index) => (
          <CodeBlockLine key={index}>{line}</CodeBlockLine>
        ))}
      </CodeBlockContent>
    </CodeBlock>
  );
}

function MarkdownCode({ node: _node, className, children, ...props }: React.ComponentProps<"code"> & ExtraProps) {
  // Streamdown marks fenced code with data-block. Everything else is inline.
  if (!("data-block" in props)) {
    return (
      <code className="rounded-sm bg-muted px-1 py-0.5 font-mono text-[0.9em]" {...props}>
        {children}
      </code>
    );
  }
  return (
    <MarkdownCodeBlock
      code={typeof children === "string" ? children : ""}
      language={/language-(\S+)/.exec(className ?? "")?.[1] ?? ""}
    />
  );
}

const components = { code: MarkdownCode };

/** Relative links ride through link hardening under this origin. */
const LOCAL_LINK = "https://local.link/";

/** `[text](references/a.md)` → an absolute URL the hardening keeps. */
function markLocalLinks(markdown: string): string {
  return markdown.replace(/\]\((?!(?:[a-z][a-z0-9+.-]*:|#|\/\/))([^)\s]+)\)/gi, (_, href: string) => `](${LOCAL_LINK}${encodeURIComponent(href)})`);
}

/** The agent's reply as markdown (shadcn/ui AI Elements · Message). */
export const Markdown = React.memo(function Markdown({
  children,
  className,
  streaming = false,
  onLocalLink,
}: {
  children: string;
  className?: string;
  /** Pass while the reply streams, so incomplete fences render safely. */
  streaming?: boolean;
  /** Relative links (`references/a.md`) call this instead of being blocked. */
  onLocalLink?(href: string): void;
}) {
  const localComponents = React.useMemo(
    () =>
      onLocalLink
        ? {
            ...components,
            a: ({ node: _node, href, children: label, ...props }: React.ComponentProps<"a"> & ExtraProps) =>
              href?.startsWith(LOCAL_LINK) ? (
                <button
                  type="button"
                  onClick={() => onLocalLink(decodeURIComponent(href.slice(LOCAL_LINK.length)))}
                  className="cursor-pointer text-link underline-offset-4 hover:underline"
                >
                  {label}
                </button>
              ) : (
                <a href={href} {...props}>
                  {label}
                </a>
              ),
          }
        : components,
    [onLocalLink],
  );
  // Streamed text is revealed at a steady pace rather than in network bursts.
  const smooth = useSmoothText(children, streaming);
  const text = onLocalLink ? markLocalLinks(smooth.text) : smooth.text;
  return (
    <div
      data-selectable
      className={cn(
        "max-w-none text-sm leading-6 text-foreground",
        "[&_a]:text-link [&_a]:underline-offset-4 hover:[&_a]:underline",
        "[&_ol]:list-decimal [&_ol]:pl-5 [&_ul]:list-disc [&_ul]:pl-5 [&_li]:my-1",
        "[&_h1]:text-xl [&_h1]:font-semibold [&_h1]:tracking-tight [&_h2]:text-base [&_h2]:font-semibold [&_h3]:font-medium",
        "[&_p]:my-2 [&>*:first-child]:mt-0 [&>*:last-child]:mb-0",
        className,
      )}
    >
      <Streamdown controls={false} components={localComponents} isAnimating={streaming || smooth.revealing}>
        {text}
      </Streamdown>
    </div>
  );
});
