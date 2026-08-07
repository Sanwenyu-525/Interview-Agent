import { useEffect, useRef, useState } from "react";

// 即时提示状态：成功类短提示自动消失；persist 用于错误等需要保留到下一次操作的消息
export function useAutoDismiss(initial = "", durationMs = 2200) {
  const [notice, setNotice] = useState(initial);
  const timerRef = useRef(null);

  useEffect(() => () => { if (timerRef.current) clearTimeout(timerRef.current); }, []);

  function showNotice(message, { persist = false } = {}) {
    if (timerRef.current) clearTimeout(timerRef.current);
    setNotice(message);
    if (persist || !String(message)) return;
    timerRef.current = setTimeout(() => setNotice(""), durationMs);
  }

  return [notice, showNotice];
}