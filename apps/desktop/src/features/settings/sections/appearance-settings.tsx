import * as React from "react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ColorPicker } from "../color-picker";
import { Radio } from "@base-ui/react/radio";
import { RadioGroup } from "@base-ui/react/radio-group";
import {
  CheckIcon,
  MonitorIcon,
  MoonIcon,
  PaletteIcon,
  PipetteIcon,
  RotateCcwIcon,
  SunIcon,
  type LucideIcon,
} from "lucide-react";
import { useTheme, type Theme } from "@/components/theme-provider";
import { Button } from "@/components/ui/button";
import { setZoom } from "@/features/shell/app-commands";
import { cn } from "@/lib/utils";
import {
  ACCENTS,
  APPEARANCE_DEFAULTS,
  CHAT_WIDTHS,
  CODE_FONTS,
  CUSTOM_ACCENT,
  INTERFACE_FONTS,
  accentColors,
  useAppearanceStore,
  type ChatWidth,
  type MotionPreference,
} from "@/stores/appearance-store";
import { useUiStore } from "@/stores/ui-store";
import {
  ChoiceCard,
  ChoiceCards,
  Segmented,
  SettingsGroup,
  SettingsHeader,
  SettingsRow,
  StepSlider,
} from "../settings-controls";

const SCHEMES: { value: Theme; label: string; icon: LucideIcon }[] = [
  { value: "system", label: "System", icon: MonitorIcon },
  { value: "light", label: "Light", icon: SunIcon },
  { value: "dark", label: "Dark", icon: MoonIcon },
];

/** Interface size stops: the window zoom levels between 80% and 150%. */
const SIZE_STOPS = [0.8, 0.9, 1, 1.1, 1.25, 1.5];

const MOTION: { value: MotionPreference; label: string }[] = [
  { value: "system", label: "System" },
  { value: "reduced", label: "Reduced" },
  { value: "full", label: "Full" },
];

const percent = (value: number) => `${Math.round(value * 100)}%`;

/** A small picture of the app in one colour scheme, for the scheme cards. */
function SchemePreview({ scheme }: { scheme: "light" | "dark" | "split" }) {
  const pane = (dark: boolean) => (
    <div className={cn("flex h-full flex-1 gap-1 p-1.5", dark ? "bg-[#0a0a0a]" : "bg-[#f2f2f2]")}>
      <div className="flex w-1/3 flex-col gap-1">
        <div className={cn("h-1 w-3/4 rounded-full", dark ? "bg-white/25" : "bg-black/20")} />
        <div className={cn("h-1 w-1/2 rounded-full", dark ? "bg-white/15" : "bg-black/10")} />
        <div className={cn("h-1 w-2/3 rounded-full", dark ? "bg-white/15" : "bg-black/10")} />
      </div>
      <div className={cn("flex flex-1 flex-col justify-end gap-1 rounded-sm p-1", dark ? "bg-[#161616]" : "bg-white")}>
        <div className={cn("h-1 w-4/5 rounded-full", dark ? "bg-white/20" : "bg-black/15")} />
        <div className="h-1.5 w-1/3 self-end rounded-full bg-brand" />
      </div>
    </div>
  );
  return (
    <div className="flex h-16 w-full overflow-hidden rounded-md shadow-hairline">
      {scheme === "split" ? (
        <>
          {pane(false)}
          {pane(true)}
        </>
      ) : (
        pane(scheme === "dark")
      )}
    </div>
  );
}

function ColorScheme() {
  const { theme, setTheme } = useTheme();
  return (
    <SettingsRow
      labelId="scheme-label"
      label="Color scheme"
      description="Follow the system setting or pin the app to light or dark."
    >
      <RadioGroup
        value={theme}
        onValueChange={(value) => setTheme(value as Theme)}
        aria-labelledby="scheme-label"
        className="grid grid-cols-3 gap-3"
      >
        {SCHEMES.map(({ value, label, icon: Icon }) => (
          <Radio.Root
            key={value}
            value={value}
            className={cn(
              "group/scheme flex flex-col gap-2 rounded-lg p-1.5 text-left outline-none transition-colors",
              "hover:bg-accent/60 data-checked:bg-brand/5",
              "focus-visible:shadow-[0_0_0_2px_var(--background),0_0_0_4px_var(--ring)]",
            )}
          >
            <div className="rounded-md ring-offset-2 ring-offset-card group-data-checked/scheme:ring-2 group-data-checked/scheme:ring-brand">
              <SchemePreview scheme={value === "system" ? "split" : value} />
            </div>
            <span className="flex items-center gap-1.5 px-0.5 text-[13px] font-medium text-muted-foreground group-data-checked/scheme:text-foreground">
              <Icon className="size-3.5" />
              {label}
            </span>
          </Radio.Root>
        ))}
      </RadioGroup>
    </SettingsRow>
  );
}

function AccentPicker() {
  const accent = useAppearanceStore((s) => s.accent);
  const customAccent = useAppearanceStore((s) => s.customAccent);
  const setAccent = useAppearanceStore((s) => s.setAccent);
  const setCustomAccent = useAppearanceStore((s) => s.setCustomAccent);
  const { resolved } = useTheme();
  const [pickerOpen, setPickerOpen] = React.useState(false);
  const current = accent === CUSTOM_ACCENT ? "Custom" : (ACCENTS.find((a) => a.id === accent)?.label ?? "Blue");

  const swatch = cn(
    "relative flex size-7 items-center justify-center rounded-full outline-none transition-transform",
    "shadow-[inset_0_0_0_1px_rgb(0_0_0/0.12)] hover:scale-110",
    "data-checked:shadow-[0_0_0_2px_var(--card),0_0_0_4px_var(--swatch)]",
    "focus-visible:shadow-[0_0_0_2px_var(--card),0_0_0_4px_var(--ring)]",
  );

  return (
    <SettingsRow
      labelId="accent-label"
      label="Accent"
      description="Links, focus rings, text selection, check marks, progress and active tabs. Buttons stay neutral."
      control={<span className="font-mono text-xs text-muted-foreground">{current}</span>}
    >
      <RadioGroup
        value={accent}
        onValueChange={(value) => {
          if (value === CUSTOM_ACCENT) setPickerOpen(true);
          setAccent(value as string);
        }}
        aria-labelledby="accent-label"
        className="flex flex-wrap items-center gap-2.5"
      >
        {ACCENTS.map((option) => {
          const color = resolved === "dark" ? option.dark : option.light;
          return (
            <Radio.Root
              key={option.id}
              value={option.id}
              aria-label={option.label}
              title={option.label}
              className={swatch}
              style={{ background: color, "--swatch": color } as React.CSSProperties}
            >
              {accent === option.id && (
                <CheckIcon
                  className={cn("size-3.5", option.id === "graphite" ? "text-background" : "text-white")}
                  strokeWidth={3}
                />
              )}
            </Radio.Root>
          );
        })}
        <Radio.Root
          value={CUSTOM_ACCENT}
          aria-label="Custom colour"
          title="Custom colour"
          onClick={() => setPickerOpen(true)}
          className={swatch}
          style={
            {
              background:
                accent === CUSTOM_ACCENT
                  ? customAccent
                  : "conic-gradient(from 180deg, #e5484d, #ff990a, #6cda75, #3ec5e0, #3291ff, #bf89ec, #e5484d)",
              "--swatch": accent === CUSTOM_ACCENT ? customAccent : "var(--muted-foreground)",
            } as React.CSSProperties
          }
        >
          <PipetteIcon className="size-3.5 text-white drop-shadow-[0_1px_1px_rgb(0_0_0/0.5)]" strokeWidth={2.5} />
        </Radio.Root>
        <Popover open={pickerOpen} onOpenChange={setPickerOpen}>
          <PopoverTrigger aria-hidden tabIndex={-1} className="pointer-events-none -ml-2.5 size-0 opacity-0" />
          <PopoverContent align="start" className="w-auto p-3">
            <ColorPicker value={customAccent} onChange={setCustomAccent} />
          </PopoverContent>
        </Popover>
      </RadioGroup>
      <AccentSample />
    </SettingsRow>
  );
}

/** The accent applied to the things it colours. */
function AccentSample() {
  const accent = useAppearanceStore((s) => s.accent);
  const customAccent = useAppearanceStore((s) => s.customAccent);
  const colors = accentColors({ accent, customAccent });
  return (
    <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-3 rounded-lg bg-muted/60 px-4 py-3 text-[13px] shadow-hairline">
      <span className="inline-flex items-center gap-1.5">
        <CheckIcon className="size-3.5 text-brand" strokeWidth={2.5} />
        Selected
      </span>
      <span className="h-1.5 w-16 overflow-hidden rounded-full bg-muted shadow-hairline">
        <span className="block h-full w-2/3 bg-brand" />
      </span>
      <span className="text-link underline-offset-2 hover:underline">A link to docs</span>
      <span className="inline-flex h-7 items-center rounded-md bg-background px-3 shadow-[0_0_0_2px_var(--muted),0_0_0_4px_var(--ring)]">
        Focused
      </span>
      <span>
        Some <span className="rounded-[2px] bg-brand/25 px-0.5">selected</span> text
      </span>
      <span className="ml-auto font-mono text-[11px] text-muted-foreground uppercase">
        {colors.light === colors.dark ? colors.light : `${colors.light} · ${colors.dark}`}
      </span>
    </div>
  );
}

function Typography() {
  const interfaceFont = useAppearanceStore((s) => s.interfaceFont);
  const codeFont = useAppearanceStore((s) => s.codeFont);
  const setInterfaceFont = useAppearanceStore((s) => s.setInterfaceFont);
  const setCodeFont = useAppearanceStore((s) => s.setCodeFont);
  const zoom = useUiStore((s) => s.zoom);

  return (
    <SettingsGroup title="Typography">
      <SettingsRow
        labelId="font-label"
        label="Interface font"
        description="Applies to every surface except code, which keeps the code font."
      >
        <ChoiceCards
          value={interfaceFont}
          onValueChange={setInterfaceFont}
          labelledBy="font-label"
          className="grid-cols-1 sm:grid-cols-3"
        >
          {INTERFACE_FONTS.map((font) => (
            <ChoiceCard
              key={font.id}
              value={font.id}
              preview="Aa"
              title={font.label}
              description={font.description}
              previewStyle={{ fontFamily: font.stack }}
            />
          ))}
        </ChoiceCards>
      </SettingsRow>

      <SettingsRow
        labelId="code-font-label"
        label="Code font"
        description="Code blocks, diffs, tool output and the terminal."
      >
        <ChoiceCards
          value={codeFont}
          onValueChange={setCodeFont}
          labelledBy="code-font-label"
          className="grid-cols-1 sm:grid-cols-2"
        >
          {CODE_FONTS.map((font) => (
            <ChoiceCard
              key={font.id}
              value={font.id}
              preview="{ }"
              title={font.label}
              description={font.description}
              previewStyle={{ fontFamily: font.stack }}
            />
          ))}
        </ChoiceCards>
      </SettingsRow>

      <SettingsRow
        label="Interface size"
        description={
          <>
            100% is the balanced default. Same as View → Zoom, or <kbd className="font-mono text-xs">Ctrl</kbd> with{" "}
            <kbd className="font-mono text-xs">+</kbd> / <kbd className="font-mono text-xs">−</kbd>.
          </>
        }
        control={<span className="font-mono text-xs text-muted-foreground tabular-nums">{percent(zoom)}</span>}
      >
        <StepSlider
          label="Interface size"
          stops={SIZE_STOPS}
          value={zoom}
          defaultValue={1}
          onValueChange={setZoom}
          format={percent}
        />
      </SettingsRow>
    </SettingsGroup>
  );
}

function Layout() {
  const chatWidth = useAppearanceStore((s) => s.chatWidth);
  const setChatWidth = useAppearanceStore((s) => s.setChatWidth);
  const motion = useAppearanceStore((s) => s.motion);
  const setMotion = useAppearanceStore((s) => s.setMotion);

  return (
    <SettingsGroup title="Layout & motion">
      <SettingsRow
        labelId="width-label"
        label="Conversation width"
        description="How wide messages and the composer run in the chat column."
        control={
          <Segmented<ChatWidth>
            value={chatWidth}
            onValueChange={setChatWidth}
            labelledBy="width-label"
            options={CHAT_WIDTHS.map((w) => ({ value: w.id, label: w.label }))}
          />
        }
      />
      <SettingsRow
        labelId="motion-label"
        label="Animations"
        description="Panel transitions, menus and list reveals. System follows your operating system's reduced-motion setting."
        control={
          <Segmented<MotionPreference>
            value={motion}
            onValueChange={setMotion}
            labelledBy="motion-label"
            options={MOTION}
          />
        }
      />
    </SettingsGroup>
  );
}

export function AppearanceSettings() {
  const state = useAppearanceStore();
  const zoom = useUiStore((s) => s.zoom);
  const { theme, setTheme } = useTheme();
  const isDefault =
    theme === "system" &&
    zoom === 1 &&
    (Object.keys(APPEARANCE_DEFAULTS) as (keyof typeof APPEARANCE_DEFAULTS)[]).every(
      (key) => key === "customAccent" || state[key] === APPEARANCE_DEFAULTS[key],
    );

  function resetAll() {
    state.reset();
    setTheme("system");
    setZoom(1);
  }

  return (
    <div className="flex flex-col gap-8">
      <SettingsHeader
        icon={PaletteIcon}
        title="Appearance"
        description="Colors, type and motion. Changes apply immediately and stay on this machine."
      >
        <Button variant="ghost" size="sm" disabled={isDefault} onClick={resetAll} className="text-muted-foreground">
          <RotateCcwIcon />
          Reset
        </Button>
      </SettingsHeader>

      <SettingsGroup title="Theme">
        <ColorScheme />
        <AccentPicker />
      </SettingsGroup>

      <Typography />
      <Layout />
    </div>
  );
}
