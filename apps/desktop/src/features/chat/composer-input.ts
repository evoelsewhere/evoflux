// What goes into a message besides typed text: pasted or dropped pictures,
// files and long pasted text, and how they ride along when it is sent. No React.

import { invoke } from "@tauri-apps/api/core";
import type { PromptAttachment } from "@/components/ai-elements/prompt-input";
import { readFile } from "@/features/files/fs";
import { baseName } from "@/lib/format";
import type { PromptImage } from "@/stores/engine-store";

/** The engine takes at most 4 pictures, 256 KiB each and 512 KiB in all (rpc/prompt_content.rs). */
export const MAX_IMAGES = 4;
const MAX_IMAGE_BYTES = 250 * 1024;
const MAX_TOTAL_IMAGE_BYTES = 500 * 1024;
/** Longest side sent; larger pictures are scaled down (the model sees ~1.5k px anyway). */
const MAX_SIDE = 1568;
/** Text in a message with pictures is capped at 32 KiB; longer pasted text goes as a file. */
const MAX_BLOCK_TEXT = 30 * 1024;

/** Pasted text this long (characters or lines) becomes an attachment instead of filling the field. */
export const isLongPaste = (text: string) => text.length > 2500 || text.split("\n").length > 40;

const IMAGE_EXT = /\.(png|jpe?g|gif|webp|bmp)$/i;

let pasted = 0;
const nextId = (kind: string) => `${kind}-${Date.now().toString(36)}-${++pasted}`;

function imageAttachment(blob: Blob, name: string, path?: string): PromptAttachment {
  return { id: path ?? nextId("image"), name, kind: "image", blob, preview: URL.createObjectURL(blob), path };
}

export function textAttachment(text: string): PromptAttachment {
  const lines = text.split("\n").length;
  return { id: nextId("text"), name: `Pasted text · ${lines} ${lines === 1 ? "line" : "lines"}`, kind: "text", text };
}

/** A file or folder on disk, referenced by path. */
export const fileAttachment = (path: string): PromptAttachment => ({ id: path, name: baseName(path), kind: "file", path });

/** Let go of a removed attachment's thumbnail. */
export function releaseAttachment(file: PromptAttachment) {
  if (file.preview?.startsWith("blob:")) URL.revokeObjectURL(file.preview);
}

function toBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).replace(/^data:[^,]*,/, ""));
    reader.onerror = () => reject(reader.error ?? new Error("could not read the file"));
    reader.readAsDataURL(blob);
  });
}

/** A file with no path of its own (from the clipboard): saved to the app's cache. */
async function savedFile(file: File): Promise<PromptAttachment> {
  const path = await invoke<string>("fs_save_paste", { name: file.name || "pasted", data: await toBase64(file) });
  return fileAttachment(path);
}

/** Pictures and files from a paste or a browser drop (`DataTransfer`). Empty when it holds only text. */
export async function attachmentsFromTransfer(data: DataTransfer): Promise<PromptAttachment[]> {
  const files = [...data.files];
  if (files.length === 0) {
    for (const item of data.items) {
      const file = item.kind === "file" ? item.getAsFile() : null;
      if (file) files.push(file);
    }
  }
  const out: PromptAttachment[] = [];
  for (const file of files) {
    if (file.type.startsWith("image/")) {
      out.push(imageAttachment(file, file.name && file.name !== "image.png" ? file.name : `Pasted image ${++pasted}.png`));
    } else {
      out.push(await savedFile(file));
    }
  }
  return out;
}

/** Files dropped from the system (paths): pictures are shown and sent, the rest referenced. */
export async function attachmentsFromPaths(paths: string[]): Promise<PromptAttachment[]> {
  const out: PromptAttachment[] = [];
  for (const path of paths) {
    if (IMAGE_EXT.test(path)) {
      const content = await readFile(path).catch(() => null);
      if (content?.kind === "image") {
        const blob = await (await fetch(content.dataUrl)).blob();
        out.push(imageAttachment(blob, baseName(path), path));
        continue;
      }
    }
    out.push(fileAttachment(path));
  }
  return out;
}

/** Encode a picture as PNG or JPEG within `budget` bytes, scaling it down as needed. */
export async function encodeImage(blob: Blob, budget = MAX_IMAGE_BYTES): Promise<PromptImage> {
  const bitmap = await createImageBitmap(blob);
  try {
    let scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
    if (scale === 1 && blob.size <= budget && (blob.type === "image/png" || blob.type === "image/jpeg")) {
      return { data: await toBase64(blob), mimeType: blob.type };
    }
    for (let attempt = 0; attempt < 8; attempt++) {
      const width = Math.max(1, Math.round(bitmap.width * scale));
      const height = Math.max(1, Math.round(bitmap.height * scale));
      const canvas = new OffscreenCanvas(width, height);
      const context = canvas.getContext("2d");
      if (!context) throw new Error("could not prepare the picture");
      for (const [type, quality] of [
        ["image/png", undefined],
        ["image/jpeg", 0.9],
        ["image/jpeg", 0.78],
        ["image/jpeg", 0.62],
      ] as const) {
        context.clearRect(0, 0, width, height);
        // JPEG has no transparency: put it on white rather than black.
        if (type === "image/jpeg") {
          context.fillStyle = "#ffffff";
          context.fillRect(0, 0, width, height);
        }
        context.drawImage(bitmap, 0, 0, width, height);
        const out = await canvas.convertToBlob({ type, quality });
        if (out.size <= budget) return { data: await toBase64(out), mimeType: type };
      }
      scale *= 0.75;
    }
    throw new Error("The picture is too large to send.");
  } finally {
    bitmap.close();
  }
}

/** Attached paths, one `@path` per line after the text (the agent reads them with its tools). */
const REF_LINE = /^@(.+)$/;
const PASTED = /<pasted-text lines="(\d+)">\n([\s\S]*?)\n<\/pasted-text>/g;

/** The message and pictures to send for `text` and its attachments. */
export async function buildPrompt(
  text: string,
  attachments: PromptAttachment[],
): Promise<{ text: string; images: PromptImage[] }> {
  const pictures = attachments.filter((file) => file.kind === "image" && file.blob);
  if (pictures.length > MAX_IMAGES) throw new Error(`At most ${MAX_IMAGES} pictures fit in one message.`);
  const budget = Math.min(MAX_IMAGE_BYTES, Math.floor(MAX_TOTAL_IMAGE_BYTES / Math.max(1, pictures.length)));
  const images: PromptImage[] = [];
  for (const picture of pictures) images.push(await encodeImage(picture.blob!, budget));

  const texts = attachments.filter((file) => file.kind === "text" && file.text);
  const inline = texts.reduce((sum, file) => sum + file.text!.length, text.length);
  const pastedBlocks: string[] = [];
  const refs: string[] = [];
  for (const file of texts) {
    if (images.length > 0 && inline > MAX_BLOCK_TEXT) {
      // Too long next to pictures: send it as a file the agent can read.
      const blob = new Blob([file.text!], { type: "text/plain" });
      const saved = await savedFile(new File([blob], "pasted.txt"));
      refs.push(`@${saved.path}`);
    } else {
      pastedBlocks.push(`<pasted-text lines="${file.text!.split("\n").length}">\n${file.text}\n</pasted-text>`);
    }
  }
  for (const file of attachments) {
    if (file.kind === "text") continue;
    // A pasted picture is sent as a picture only; a dropped one also says where it is.
    if (file.kind === "image" && !file.path) continue;
    refs.push(`@${file.path ?? file.id}`);
  }
  const parts = [text.trim(), ...pastedBlocks, refs.join("\n")].filter(Boolean);
  return { text: parts.join("\n\n"), images };
}

/** A sent message taken apart for display: its text, pasted blocks and attached paths. */
export function splitPrompt(message: string): { text: string; pasted: { lines: number; text: string }[]; files: string[] } {
  const pasted: { lines: number; text: string }[] = [];
  let text = message.replace(PASTED, (_, lines: string, body: string) => {
    pasted.push({ lines: Number(lines), text: body });
    return "";
  });
  const lines = text.replace(/\s+$/, "").split("\n");
  const files: string[] = [];
  // Older messages put several references on one line, space-separated.
  if (lines.length > 0 && /^@\S+(\s+@\S+)+$/.test(lines[lines.length - 1].trim())) {
    files.push(...lines.pop()!.trim().split(/\s+/).map((ref) => ref.slice(1)));
  } else {
    while (lines.length > 0) {
      const match = REF_LINE.exec(lines[lines.length - 1].trim());
      if (!match) break;
      files.unshift(match[1]);
      lines.pop();
    }
  }
  text = lines.join("\n").trim();
  return { text, pasted, files };
}
