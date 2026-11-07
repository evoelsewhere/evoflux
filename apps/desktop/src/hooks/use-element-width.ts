import * as React from "react";

/** Live width of an element, from a ResizeObserver. */
export function useElementWidth<T extends HTMLElement>(): [React.RefCallback<T>, number] {
  const [width, setWidth] = React.useState(0);
  const observer = React.useRef<ResizeObserver | null>(null);

  const ref = React.useCallback((node: T | null) => {
    observer.current?.disconnect();
    if (!node) return;
    observer.current = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.current.observe(node);
    setWidth(node.getBoundingClientRect().width);
  }, []);

  React.useEffect(() => () => observer.current?.disconnect(), []);
  return [ref, width];
}
