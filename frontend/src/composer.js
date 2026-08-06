export function insertMarkdown(value, selectionStart, selectionEnd, marker, placeholder = "重点") {
  const text = String(value ?? "");
  const start = Math.max(0, Math.min(selectionStart ?? text.length, text.length));
  const end = Math.max(start, Math.min(selectionEnd ?? start, text.length));
  const selected = text.slice(start, end) || placeholder;
  const replacement = `${marker}${selected}${marker}`;
  const nextValue = `${text.slice(0, start)}${replacement}${text.slice(end)}`;
  const hasSelection = end > start;

  return {
    value: nextValue,
    selectionStart: hasSelection ? start + replacement.length : start + marker.length,
    selectionEnd: hasSelection ? start + replacement.length : start + marker.length + selected.length,
  };
}
