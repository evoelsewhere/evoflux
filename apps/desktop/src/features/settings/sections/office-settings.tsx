import { FileTextIcon } from "lucide-react";
import { OfficeActions, OfficeError, OfficeProgress } from "@/components/office-install";
import { formatBytes } from "@/lib/format";
import { useOffice } from "@/stores/office-store";
import { SettingsGroup, SettingsHeader, SettingsRow } from "../settings-controls";

// The renderer behind the Files tool's preview of Word, PowerPoint and Excel
// files: a trimmed LibreOffice that is downloaded only when asked, checked
// against a checksum compiled into evo, and also made available to the agent's
// shell as `EVO_SOFFICE`. docs/features/office/sdd.md.

function stateLine(status: ReturnType<typeof useOffice>["status"]): string {
  if (!status) return "Checking…";
  if (status.installedVersion) return `Installed · LibreOffice ${status.installedVersion}`;
  if (!status.available) return "Not available for this platform";
  const size = status.installBytes ? `, ${formatBytes(status.installBytes)} on disk` : "";
  return `Not installed · ${formatBytes(status.downloadBytes ?? 0)} download${size}`;
}

export function OfficeSettings() {
  const { status, error, ready } = useOffice();
  const running = !!status?.job && status.job.phase !== "failed";
  return (
    <div className="flex flex-col gap-8">
      <SettingsHeader
        icon={FileTextIcon}
        title="Office"
        description="Preview .docx, .pptx and .xlsx files exactly as Office lays them out, and let the agent convert and check documents with LibreOffice."
      />
      <SettingsGroup
        title="Renderer"
        description="A LibreOffice build evo downloads once, from its own release, and verifies before use. Nothing is downloaded until you install it."
      >
        <SettingsRow label="LibreOffice runtime" description={stateLine(status)} control={<OfficeActions />}>
          {running && status?.job && <OfficeProgress job={status.job} />}
          <OfficeError job={status?.job ?? null} />
          {error && (
            <p className="text-[13px] text-destructive">
              {ready ? error : "Open a chat to manage the renderer: it runs in the chat's engine."}
            </p>
          )}
        </SettingsRow>
      </SettingsGroup>
      <SettingsGroup title="For the agent" description="What the agent's shell sees once the renderer is installed.">
        <SettingsRow
          label="Environment"
          description={
            <>
              <code className="font-mono">EVO_SOFFICE</code> holds the path of <code className="font-mono">soffice</code>, and its folder
              is added to the end of <code className="font-mono">PATH</code>. The Word, PowerPoint and Excel skills use it to render and
              check documents. They ship with evo.
            </>
          }
        />
      </SettingsGroup>
    </div>
  );
}
