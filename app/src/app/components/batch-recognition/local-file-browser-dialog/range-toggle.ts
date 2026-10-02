/**
 * Checkbox click with Shift+click range selection. The anchor is the last item
 * clicked; a Shift+click applies the anchor click's resulting state (ticked or
 * unticked) to every item between the two, inclusive. Returns the new anchor.
 */
export function rangeToggle(
  items: string[], clicked: string, anchor: string | null, shift: boolean, selected: Set<string>,
): string {
  const to = items.indexOf(clicked);
  const from = anchor === null ? -1 : items.indexOf(anchor);
  if (shift && from >= 0 && to >= 0) {
    const select = selected.has(anchor as string);
    for (let i = Math.min(from, to); i <= Math.max(from, to); i++) {
      select ? selected.add(items[i]) : selected.delete(items[i]);
    }
  } else {
    selected.has(clicked) ? selected.delete(clicked) : selected.add(clicked);
  }
  return clicked;
}
