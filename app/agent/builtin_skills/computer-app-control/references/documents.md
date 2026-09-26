# Documents and text editors

A document body (Word, Notepad, a mail compose area, a code editor) takes
typed text at its caret and formatting from shortcuts.

## Place the caret

- Click the body by ref, or press `ctrl+end` for the end of the document and
  `ctrl+home` for the start. Work from a known position rather than
  wherever the caret happens to be.
- To replace everything, `ctrl+a` then `type`. Do it only when the task is a
  full replacement; otherwise add to what the user wrote.

## Type

- `type` sends the text with its line breaks as Enter presses, so a whole
  paragraph or list goes in one action. In web-based editors (mail in a
  browser, Teams, Slack) a line break is Shift+Enter instead; see
  [web-content.md](web-content.md).
- When the field reports its text, the result says whether the text arrived
  as typed (`confirmed`). A miss is reported, never retyped: check with a
  snapshot, then correct only what is missing.
- Long text is fine in one `type`, up to the tool's limit per call.

## Format

Select with `shift` plus arrows, `shift+end` or `shift+home`, or
`ctrl+shift` plus arrows for whole words, then apply a shortcut: `ctrl+b`
bold, `ctrl+i` italic, `ctrl+u` underline. Headings, lists and styles are
commands: `find` them by name and `invoke` the ref.

## Save

`ctrl+s` saves a document that already has a file. A new document opens a
save dialog; see [forms-and-dialogs.md](forms-and-dialogs.md) for filling it.
Say where the file was saved.
