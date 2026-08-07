import { useCallback, useRef, useState } from "react";

// 通用分栏拖拽 hook：pointer 拖拽 + 键盘方向键 + 双击重置 + clamp + 可选持久化
// direction 为 1 时向右拖拽增宽，为 -1 时向右拖拽收窄（用于右侧面板）
export default function usePanelResize({
  value,
  onChange,
  min = -Infinity,
  max = Infinity,
  direction = 1,
  step = 8,
  onReset,
  storageKey = null,
}) {
  const dragRef = useRef(null);
  const valueRef = useRef(value);
  valueRef.current = value;
  const [resizing, setResizing] = useState(false);

  const apply = useCallback((next) => {
    const clamped = Math.max(min, Math.min(max, Math.round(next)));
    onChange(clamped);
    if (storageKey) globalThis.localStorage?.setItem(storageKey, String(clamped));
  }, [min, max, onChange, storageKey]);

  const handlePointerDown = useCallback((event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.currentTarget.focus();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    dragRef.current = { pointerId: event.pointerId, startX: event.clientX, startWidth: valueRef.current };
    setResizing(true);
  }, []);

  const handlePointerMove = useCallback((event) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    apply(drag.startWidth + (event.clientX - drag.startX) * direction);
  }, [apply, direction]);

  const handlePointerEnd = useCallback((event) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    dragRef.current = null;
    setResizing(false);
  }, []);

  const handleKeyDown = useCallback((event) => {
    if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    const physicalDelta = event.key === "ArrowRight" ? step : -step;
    apply(valueRef.current + physicalDelta * direction);
  }, [apply, direction, step]);

  const handleDoubleClick = useCallback(() => {
    if (onReset) {
      const next = onReset();
      if (next !== undefined) apply(next);
    }
  }, [onReset, apply]);

  return {
    resizing,
    handlers: {
      onPointerDown: handlePointerDown,
      onPointerMove: handlePointerMove,
      onPointerUp: handlePointerEnd,
      onPointerCancel: handlePointerEnd,
      onKeyDown: handleKeyDown,
      onDoubleClick: handleDoubleClick,
    },
  };
}
