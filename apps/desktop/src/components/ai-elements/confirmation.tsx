import { ShieldQuestionIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle } from "@/components/ui/item";

export interface ConfirmationOption {
  title: string;
  permission?: string;
}

/** Approve or deny a tool before it runs (AI Elements · Confirmation). */
export function Confirmation({
  title,
  description,
  options,
  onAnswer,
}: {
  title: string;
  description?: string;
  options: ConfirmationOption[];
  onAnswer(option: ConfirmationOption, index: number): void;
}) {
  return (
    <Item variant="outline" className="items-start shadow-hairline">
      <ItemMedia variant="icon">
        <ShieldQuestionIcon />
      </ItemMedia>
      <ItemContent>
        <ItemTitle>{title}</ItemTitle>
        {description && <ItemDescription data-selectable>{description}</ItemDescription>}
      </ItemContent>
      <ItemActions className="self-center">
        {options.map((option, index) => {
          const rejects = option.permission?.startsWith("reject") || /^(deny|reject|no)\b/i.test(option.title);
          return (
            <Button
              key={`${option.title}-${index}`}
              size="sm"
              variant={rejects ? "outline" : index === 0 ? "default" : "secondary"}
              onClick={() => onAnswer(option, index)}
            >
              {option.title}
            </Button>
          );
        })}
      </ItemActions>
    </Item>
  );
}
