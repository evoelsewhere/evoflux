import * as React from "react";
import { invoke } from "@tauri-apps/api/core";
import { HistoryIcon, SlidersHorizontalIcon } from "lucide-react";
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectSeparator, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { notify } from "@/features/notifications/notify";
import { AppIcon } from "@/features/shell/open-in-menu";
import { useOpenApps, type OpenApp } from "@/lib/open-apps";
import { inTauri, isMac } from "@/lib/platform";
import { autoOpenGeneratedEnabled, setAutoOpenGenerated } from "@/stores/office-store";
import { useUiStore } from "@/stores/ui-store";
import { SettingsGroup, SettingsHeader, SettingsRow } from "../settings-controls";

// Startup and background, applied by the shell (src-tauri/src/system.rs), and
// the Files setting to open documents the agent creates (stores/office-store.ts).

interface SystemSettings {
  runOnStartup: boolean;
  tray: boolean;
  keepAwake: boolean;
}

type Key = keyof SystemSettings;

/** Where the icon lives: the menu bar on macOS, the tray elsewhere. */
const TRAY = isMac ? "menu bar" : "system tray";
const TRAY_AREA = isMac ? "menu bar" : "notification area";

function Toggle({
  id,
  settings,
  pending,
  onChange,
}: {
  id: Key;
  settings: SystemSettings | null;
  pending: Key | null;
  onChange(key: Key, enabled: boolean): void;
}) {
  return (
    <Switch
      aria-labelledby={`setting-${id}`}
      checked={settings?.[id] ?? false}
      disabled={!settings || pending === id}
      onCheckedChange={(checked) => onChange(id, checked)}
    />
  );
}

export function GeneralSettings() {
  const [settings, setSettings] = React.useState<SystemSettings | null>(null);
  const [pending, setPending] = React.useState<Key | null>(null);

  React.useEffect(() => {
    if (!inTauri) return;
    invoke<SystemSettings>("system_settings").then(setSettings).catch(() => setSettings(null));
  }, []);

  function change(key: Key, enabled: boolean) {
    setPending(key);
    setSettings((s) => (s ? { ...s, [key]: enabled } : s));
    invoke<SystemSettings>("system_set", { key, enabled })
      .then(setSettings)
      .catch((error: unknown) => {
        setSettings((s) => (s ? { ...s, [key]: !enabled } : s));
        notify({ source: "settings", level: "error", title: "Could not change the setting", body: String(error) });
      })
      .finally(() => setPending(null));
  }

  const toggle = (id: Key) => <Toggle id={id} settings={settings} pending={pending} onChange={change} />;

  // Files: open a document the agent creates (app setting `files.autoOpenGenerated`, read when one appears).
  const [autoOpen, setAutoOpen] = React.useState<boolean | null>(inTauri ? null : true);
  React.useEffect(() => {
    if (inTauri) void autoOpenGeneratedEnabled().then(setAutoOpen);
  }, []);
  function changeAutoOpen(enabled: boolean) {
    setAutoOpen(enabled);
    if (!inTauri) return;
    setAutoOpenGenerated(enabled).catch((error: unknown) => {
      setAutoOpen(!enabled);
      notify({ source: "settings", level: "error", title: "Could not change the setting", body: String(error) });
    });
  }

  return (
    <div className="flex flex-col gap-8">
      <SettingsHeader
        icon={SlidersHorizontalIcon}
        title="General"
        description={
          inTauri ? "How evo starts and what it keeps doing in the background." : "These settings need the desktop app."
        }
      />
      <SettingsGroup title="Startup">
        <SettingsRow
          labelId="setting-runOnStartup"
          label="Run on startup"
          description={
            settings && !settings.tray
              ? `Open evo when you sign in to this computer. With the ${TRAY} icon off, it opens its window.`
              : `Open evo when you sign in to this computer. It starts in the ${TRAY} without opening a window.`
          }
          control={toggle("runOnStartup")}
        />
      </SettingsGroup>
      <SettingsGroup title="Background">
        <SettingsRow
          labelId="setting-tray"
          label={`Show in ${TRAY}`}
          description={`Keep the evo icon in the ${TRAY_AREA}. Closing the window leaves evo running there, so running chats and scheduled tasks carry on. When off, closing the last window quits evo.`}
          control={toggle("tray")}
        />
        <SettingsRow
          labelId="setting-keepAwake"
          label="Keep computer awake"
          description="Stop this computer from going to sleep while evo is running, so scheduled tasks and long agent runs keep going while you are away. The display can still turn off."
          control={toggle("keepAwake")}
        />
      </SettingsGroup>
      <SettingsGroup title="Workspace">
        <OpenInDefaultRow />
      </SettingsGroup>
      <SettingsGroup title="Files">
        <SettingsRow
          labelId="setting-autoOpenGenerated"
          label="Open generated documents automatically"
          description="When the agent creates a Word, Excel or PowerPoint file while it works, open it in Files so you can watch it being built. Another side-panel tool you are using stays in front."
          control={
            <Switch
              aria-labelledby="setting-autoOpenGenerated"
              checked={autoOpen ?? true}
              disabled={autoOpen === null}
              onCheckedChange={changeAutoOpen}
            />
          }
        />
      </SettingsGroup>
    </div>
  );
}

/** Select value for "follow the app used last". */
const LAST_USED = "__last";

/**
 * The app the toolbar's "Open in" button opens the workspace in: one of the
 * apps the shell found, or the one used last (the default).
 */
function OpenInDefaultRow() {
  const apps = useOpenApps();
  const defaultId = useUiStore((s) => s.openInDefault);
  const setDefault = useUiStore((s) => s.setOpenInDefault);
  // A default whose app is gone (uninstalled) reads as "Last used", as the toolbar does.
  const chosen = apps.find((a) => a.id === defaultId);
  const value = chosen ? chosen.id : LAST_USED;
  const places = apps.filter((a) => a.kind !== "terminal");
  const terminals = apps.filter((a) => a.kind === "terminal");
  const items = [{ value: LAST_USED, label: "Last used" }, ...apps.map((a) => ({ value: a.id, label: a.name }))];

  const option = (app: OpenApp) => (
    <SelectItem key={app.id} value={app.id}>
      <AppIcon app={app} />
      {app.name}
    </SelectItem>
  );

  return (
    <SettingsRow
      labelId="setting-openInDefault"
      label="Default Open in app"
      description="Where the toolbar's Open in button opens the workspace folder. Last used follows the app you picked from its menu most recently."
      control={
        <Select
          value={value}
          items={items}
          disabled={!inTauri || apps.length === 0}
          onValueChange={(next) => setDefault(next && next !== LAST_USED ? String(next) : null)}
        >
          <SelectTrigger aria-labelledby="setting-openInDefault" className="w-52">
            <SelectValue>
              {(current: string) => {
                const app = apps.find((a) => a.id === current);
                return (
                  <span className="flex min-w-0 items-center gap-2">
                    {app ? <AppIcon app={app} /> : <HistoryIcon className="size-4 shrink-0 text-muted-foreground" />}
                    <span className="truncate">{app?.name ?? "Last used"}</span>
                  </span>
                );
              }}
            </SelectValue>
          </SelectTrigger>
          <SelectContent alignItemWithTrigger={false} align="end">
            <SelectItem value={LAST_USED}>
              <HistoryIcon className="text-muted-foreground" />
              Last used
            </SelectItem>
            {places.length > 0 && (
              <>
                <SelectSeparator />
                <SelectGroup>
                  <SelectLabel>Apps</SelectLabel>
                  {places.map(option)}
                </SelectGroup>
              </>
            )}
            {terminals.length > 0 && (
              <>
                <SelectSeparator />
                <SelectGroup>
                  <SelectLabel>Terminals</SelectLabel>
                  {terminals.map(option)}
                </SelectGroup>
              </>
            )}
          </SelectContent>
        </Select>
      }
    />
  );
}
