import * as React from "react";
import { invoke } from "@tauri-apps/api/core";
import { SlidersHorizontalIcon } from "lucide-react";
import { Switch } from "@/components/ui/switch";
import { notify } from "@/features/notifications/notify";
import { inTauri, isMac } from "@/lib/platform";
import { SettingsGroup, SettingsHeader, SettingsRow } from "../settings-controls";

// Startup and background, applied by the shell (src-tauri/src/system.rs).

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
    </div>
  );
}
