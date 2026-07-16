# Screen pattern mapping — VB6 → .NET

Required reading for `aim-target-architect` before approving any screen's mapping, per §3.13A R2 of the design doc: converting a screen means classifying it into one of these patterns and instantiating the corresponding target template — not designing a new layout per screen.

| Legacy VB6 pattern | Recognize by | Target template |
|---|---|---|
| Single-record CRUD form (bound to a `Recordset`, Save/Cancel/Delete buttons) | One record's fields on a form, a data-bound grid absent or secondary | Detail-edit template |
| List/grid form with a toolbar (`New`/`Edit`/`Delete`/`Search`) | A `MSFlexGrid`/`DataGrid` as the primary control, a filter/search box | Search-list template |
| MDI parent with child forms | `MDIForm`, child forms opened via `.Show vbModeless` inside it | Single-window shell with tabs or a persistent nav pane — record the MDI → tabs decision as a project ADR, not per screen |
| Modal parameter-entry dialog | `.Show vbModal`, a small form used to collect a few inputs before an action | Modal dialog component in the target UI kit |
| Multi-step data entry (`Next`/`Back` across several forms, shared state between them) | Several forms opened in sequence, module-level variables carrying state between them | Wizard template |
| Report / print-preview form | `Printer` object usage, or a report-generation form with a preview area | Report template (and treat the report body as a test-compare artifact — output parity matters as much as screen parity) |

If a legacy screen doesn't fit any row above, that's a signal to add a new row (and a new approved template) — deliberately, at the project level — rather than letting one screen's conversion invent an unreviewed one-off pattern.
