// Which files the document viewer shows as pages (kept apart from the viewer so
// the Files panel can decide without loading pdf.js).

/** Files rendered with the Office runtime. */
export const OFFICE_FILE = /\.(docx?|dotx|odt|pptx?|ppsx|odp|xlsx?|ods)$/i;
export const PDF_FILE = /\.pdf$/i;
export const isDocument = (path: string) => OFFICE_FILE.test(path) || PDF_FILE.test(path);
