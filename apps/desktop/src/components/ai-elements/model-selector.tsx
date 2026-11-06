import * as React from "react";
import { ProviderIcon } from "@/components/provider-icon";
import { CheckIcon, ChevronDownIcon, StarIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { InputGroupButton } from "@/components/ui/input-group";
import type { ModelDescriptor } from "@/engine/protocol";

export const modelKey = (model: { provider: string; id: string }) => `${model.provider}/${model.id}`;

const SHORT_LIST = 4;

const EFFORT_NAMES: Record<string, string> = { off: "Off", xhigh: "Extra high" };
export const effortName = (level: string) => EFFORT_NAMES[level] ?? level.charAt(0).toUpperCase() + level.slice(1);

/**
 * One menu for the model and how hard it thinks (AI Elements · Model Selector):
 * a short list of models picked with 1–4, Effort in a submenu, and every other
 * model under "More models". The trigger reads "Model Effort".
 */
export function ModelSelector({
  models,
  provider,
  modelId,
  defaultModel,
  pinned,
  thinkingLevel,
  thinkingLevels,
  disabled,
  onModelChange,
  onThinkingChange,
  onPinnedChange,
  onDefaultChange,
}: {
  models: ModelDescriptor[];
  provider?: string;
  modelId?: string;
  /** `provider/id` of the engine's default model, marked with a badge. */
  defaultModel?: string;
  /** `provider/id` keys of the short list, in its order. */
  pinned: string[];
  thinkingLevel?: string;
  thinkingLevels: string[];
  disabled?: boolean;
  onModelChange(model: ModelDescriptor): void;
  onThinkingChange(level: string): void;
  /** The short list to keep: its order stays put, a model picked from "More models" joins at the top. */
  onPinnedChange?(keys: string[]): void;
  /** Make a model the one new chats start with. */
  onDefaultChange?(model: ModelDescriptor): void;
}) {
  const [open, setOpen] = React.useState(false);
  const current = models.find((m) => m.provider === provider && m.id === modelId);
  const currentKey = current ? modelKey(current) : undefined;
  const label = current?.name || modelId || "No model";
  const showEffort = thinkingLevels.length > 1 && (current?.reasoning ?? true);
  const effort = showEffort && thinkingLevel && thinkingLevel !== "off" ? effortName(thinkingLevel) : undefined;

  // The short list: the current model, pinned ones, then the current provider's
  // models and any others, up to four.
  const shortList = React.useMemo(() => {
    const byKey = new Map(models.map((m) => [modelKey(m), m]));
    const keys: string[] = [];
    const add = (key?: string) => {
      if (key && byKey.has(key) && !keys.includes(key) && keys.length < SHORT_LIST) keys.push(key);
    };
    if (currentKey && !pinned.includes(currentKey)) add(currentKey);
    pinned.forEach(add);
    models.filter((m) => m.provider === provider).forEach((m) => add(modelKey(m)));
    models.forEach((m) => add(modelKey(m)));
    return keys.map((key) => byKey.get(key)!);
  }, [models, pinned, currentKey, provider]);

  const groups = React.useMemo(() => {
    const byProvider = new Map<string, ModelDescriptor[]>();
    for (const model of models) byProvider.set(model.provider, [...(byProvider.get(model.provider) ?? []), model]);
    return [...byProvider.entries()];
  }, [models]);

  // Picks keep the menu open (to set the effort next, say); a click outside or Esc closes it.
  function choose(model: ModelDescriptor) {
    const key = modelKey(model);
    const listed = shortList.map(modelKey);
    onPinnedChange?.(listed.includes(key) ? listed : [key, ...listed]);
    if (key !== currentKey) onModelChange(model);
  }

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger
        disabled={disabled || models.length === 0}
        render={
          <InputGroupButton
            size="sm"
            variant="ghost"
            aria-label={`Model: ${label}${effort ? `, effort ${effort}` : ""}`}
          />
        }
      >
        <span className="max-w-28 truncate @lg:max-w-44">{label}</span>
        {effort && <span className="hidden text-muted-foreground @md:inline">{effort}</span>}
        <ChevronDownIcon />
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        side="top"
        className="w-60"
        onKeyDown={(event) => {
          // 1–4 pick from the short list, as the numbers beside them say.
          const index = Number(event.key) - 1;
          if (event.ctrlKey || event.metaKey || event.altKey || !(index >= 0 && index < shortList.length)) return;
          event.preventDefault();
          choose(shortList[index]);
        }}
      >
        <DropdownMenuGroup>
          {shortList.map((model, index) => {
            const key = modelKey(model);
            const active = key === currentKey;
            return (
              <DropdownMenuItem
                key={key}
                closeOnClick={false}
                onClick={() => choose(model)}
                aria-checked={active}
                role="menuitemradio"
              >
                <ProviderIcon id={model.provider} size="xs" />
                <span className="truncate">{model.name || model.id}</span>
                {key === defaultModel && (
                  <Badge variant="outline" className="h-4 px-1.5 text-[10px] font-normal text-muted-foreground">
                    Default
                  </Badge>
                )}
                <span className="ml-auto flex w-4 justify-center text-xs text-muted-foreground tabular-nums">
                  {active ? <CheckIcon className="text-brand" /> : index + 1}
                </span>
              </DropdownMenuItem>
            );
          })}
        </DropdownMenuGroup>

        {(showEffort || models.length > shortList.length) && <DropdownMenuSeparator />}

        {showEffort && (
          <DropdownMenuSub>
            <DropdownMenuSubTrigger>
              Effort
              <span className="ml-auto text-xs text-muted-foreground">{effortName(thinkingLevel ?? "default")}</span>
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent className="w-40">
              <DropdownMenuRadioGroup
                value={thinkingLevel ?? ""}
                onValueChange={(value) => onThinkingChange(String(value))}
              >
                {thinkingLevels.map((level) => (
                  <DropdownMenuRadioItem key={level} value={level}>
                    {effortName(level)}
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>
            </DropdownMenuSubContent>
          </DropdownMenuSub>
        )}

        {models.length > shortList.length && (
          <DropdownMenuSub>
            <DropdownMenuSubTrigger>More models</DropdownMenuSubTrigger>
            <DropdownMenuSubContent className="max-h-80 w-60">
              <DropdownMenuRadioGroup
                value={currentKey ?? ""}
                onValueChange={(value) => {
                  const next = models.find((m) => modelKey(m) === value);
                  if (next) choose(next);
                }}
              >
                {groups.map(([group, items], index) => (
                  <React.Fragment key={group}>
                    {index > 0 && <DropdownMenuSeparator />}
                    <DropdownMenuGroup>
                      <DropdownMenuLabel className="flex items-center gap-2">
                        <ProviderIcon id={group} size="xs" />
                        {group}
                      </DropdownMenuLabel>
                      {items.map((model) => (
                        <DropdownMenuRadioItem key={modelKey(model)} value={modelKey(model)}>
                          <span className="truncate">{model.name || model.id}</span>
                        </DropdownMenuRadioItem>
                      ))}
                    </DropdownMenuGroup>
                  </React.Fragment>
                ))}
              </DropdownMenuRadioGroup>
            </DropdownMenuSubContent>
          </DropdownMenuSub>
        )}

        {current && onDefaultChange && currentKey !== defaultModel && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem closeOnClick={false} onClick={() => onDefaultChange(current)}>
              <StarIcon />
              <span className="truncate">Use {current.name || current.id} for new chats</span>
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
