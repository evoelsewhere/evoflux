// The Office formats the native preview renders (v3 `WorkspaceDocumentKind`
// minus PDF, which keeps the pdf.js viewer).

export type OfficeKind = "docx" | "xlsx" | "pptx";

/** Word, Excel and PowerPoint (Office Open XML) files: the native preview. */
export const NATIVE_OFFICE_FILE = /\.(docx|pptx|xlsx)$/i;

export function officeKind(path: string): OfficeKind | null {
  const match = /\.(docx|pptx|xlsx)$/i.exec(path);
  return match ? (match[1].toLowerCase() as OfficeKind) : null;
}

/** Format label and the small marker dot by the file name (the only place the format's colour shows). */
export const FORMAT_META: Record<OfficeKind, { accent: string; label: string }> = {
  docx: { accent: "#185abd", label: "Word" },
  xlsx: { accent: "#107c41", label: "Excel" },
  pptx: { accent: "#c43e1c", label: "PowerPoint" },
};
