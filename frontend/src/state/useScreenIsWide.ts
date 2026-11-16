// Широкая или узкая компоновка экрана: то же условие, что у контейнерного запроса в kit.css
import { useLayoutEffect, useState, type RefObject } from 'react';

/** Порог компоновки, как в @container screen (min-width: 800px) в kit.css */
const WIDE_MIN_WIDTH = 800;

/** Ширина ближайшего контейнера .screen, а не окна: так же решает контейнерный запрос */
export function useScreenIsWide(ref: RefObject<HTMLElement | null>): boolean {
  const [wide, setWide] = useState(false);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    const screen = element.closest<HTMLElement>('.screen') ?? document.documentElement;
    setWide(screen.clientWidth >= WIDE_MIN_WIDTH);
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) setWide(entry.contentRect.width >= WIDE_MIN_WIDTH);
    });
    observer.observe(screen);
    return () => {
      observer.disconnect();
    };
  }, [ref]);
  return wide;
}
