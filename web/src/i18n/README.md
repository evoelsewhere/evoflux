# EvoFlux i18n

The web app ships English (`en`), Vietnamese (`vi`), and Japanese (`ja`). The
selected locale is stored under `oa-locale`, applied to `<html lang>`, and used
for UI strings plus `Intl` date, time, number, and currency formatting.

`I18nProvider` supports two migration paths:

- New or behavior-sensitive UI calls `useI18n().t(...)`, `translate(...)`, or
  `translateText(...)` directly.
- Existing static UI is localized by the DOM bridge from the same catalogs.
  This includes portal content and accessible attributes. User/agent content,
  Markdown, code, editable text, and anything marked `data-i18n-ignore` are
  never translated.

Catalog maintenance:

```bash
bun run i18n:extract    # refresh English keys, preserve existing translations
bun run i18n:translate  # translate new Vietnamese/Japanese keys
bun run i18n:audit:vi   # keep technical literals/terms out of machine Vietnamese
```

The generator extracts JSX copy, common UI props, option/label collections,
dynamic templates, native prompts, and explicit translation calls. Product
terminology corrections live in `overrides.ts` so regeneration cannot replace
them. Run the Vietnamese audit after adding machine-translated messages; it
keeps developer vocabulary in English and resets code-like literals that must
never be translated.
