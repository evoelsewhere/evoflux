# Canvases, objects and apps without a tree

## Contents

- Objects on a surface
- Creating an object
- Selecting and moving
- Reading an object back
- Apps with little or no accessibility tree

## Objects on a surface

Charts, shapes, text boxes, pictures, slides and diagram nodes sit on a
surface above the content (a sheet, a page, a slide, a canvas). They are
selected, moved and resized as whole objects, and each has parts (a chart's
plot area, title and legend; a group's members) that can be selected on
their own.

## Creating an object

- Prepare what it is built from first: select the data a chart should show
  (labels and series, not totals or percentages that would dwarf or flatten
  the rest), or place the caret where a picture should go.
- Run the app's insert command, found by name or by its shortcut.
- A new object lands where the app decides, often over existing content.
  Look for the app's own placement options (a separate sheet or page, a
  position or layout setting) before moving it by hand.

## Selecting and moving

Prefer, in this order:

1. **The app's position and size fields.** Many apps have a format or
   properties pane with position, size, row or anchor fields: find them by
   name and fill them with `set_value` or `type`. Exact, and easy to read
   back.
2. **Keys on a selected object.** Arrow keys usually nudge a selected
   object; alignment and arrange commands place it relative to others.
3. **Drag.** `find` the object's frame (its bounds are in the result as
   `@x,y WxH`) and drag from an empty spot inside the frame, clear of the
   corners and edges, where resize handles are, and of inner parts, which
   move on their own. To resize, drag a handle on the edge instead. If a
   drag moved nothing, pick another empty spot rather than repeating the
   same one.

## Reading an object back

- Its bounds in a new `find` or `snapshot`, or its position and size fields,
  tell where it is. Compare them with where it must be.
- Read its content from the app too: a chart's source range or series in the
  app's data dialog, a text box's text from its field, not from a picture of
  it.
- Undo an attempt that went wrong before trying another, so failed attempts
  do not pile up.

## Apps with little or no accessibility tree

Some apps draw everything themselves: games, remote desktops, some design
and engineering tools, and custom-drawn windows. The snapshot is nearly
empty or says the app exposes no tree, so refs, `invoke` and `set_value` are
not available:

- Work from screenshots. Before every pointer action, name the point you are
  aiming at from the latest screenshot; after it, take a new screenshot and
  check the change.
- Use the keyboard where the app has shortcuts: keys do not depend on
  guessing positions.
- Keep steps smaller than usual and read back each one; there is no text
  read-back to catch a mistake later.
- Say in the report which results you could only check by eye.
