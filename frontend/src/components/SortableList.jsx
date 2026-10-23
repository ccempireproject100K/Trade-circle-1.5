import { useEffect, useRef, useState } from "react";

const move = (list, from, to) => {
  const next = [...list];
  const [moved] = next.splice(from, 1);
  next.splice(to, 0, moved);
  return next;
};

// Drag-and-drop list that works with fingers and mice (pointer events; HTML5 drag
// and drop doesn't work on phones). Items reflow live while dragging. Up/down
// buttons do the same for keyboard and screen-reader users.
export default function SortableList({ items, getKey, renderItem, onReorder, label }) {
  const [drag, setDrag] = useState(null); // { key, order } while dragging
  const listRef = useRef(null);
  const dragRef = useRef(null);
  dragRef.current = drag;
  const shown = drag ? drag.order : items;

  useEffect(() => {
    if (!drag) return undefined;

    const onMove = (event) => {
      const current = dragRef.current;
      const rows = [...listRef.current.children];
      const from = current.order.findIndex((item) => getKey(item) === current.key);
      // Target is the first row whose middle is below the pointer.
      let to = rows.findIndex((row) => {
        const box = row.getBoundingClientRect();
        return event.clientY < box.top + box.height / 2;
      });
      if (to === -1) to = rows.length - 1;
      else if (to > from) to -= 1;
      if (to !== from) setDrag({ ...current, order: move(current.order, from, to) });
    };

    const onEnd = () => {
      const { order } = dragRef.current;
      setDrag(null);
      if (order.some((item, i) => getKey(item) !== getKey(items[i]))) onReorder(order);
    };

    // Listen on the window so the drag keeps going when the finger leaves the handle.
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onEnd);
    window.addEventListener("pointercancel", onEnd);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onEnd);
      window.removeEventListener("pointercancel", onEnd);
    };
  }, [drag !== null]); // eslint-disable-line react-hooks/exhaustive-deps -- (re)attach only when a drag starts or ends

  const nudge = (index, delta) => {
    const to = index + delta;
    if (to < 0 || to >= items.length) return;
    onReorder(move(items, index, to));
  };

  return (
    <ul className="sortable" ref={listRef} aria-label={label}>
      {shown.map((item, index) => {
        const key = getKey(item);
        return (
          <li key={key} className={drag?.key === key ? "dragging" : undefined}>
            <button
              type="button"
              className="drag-handle"
              aria-label="Drag to reorder"
              onPointerDown={(event) => {
                event.preventDefault();
                setDrag({ key, order: items });
              }}
            >
              ⠿
            </button>
            <div className="grow">{renderItem(item)}</div>
            <button type="button" className="btn btn-icon" aria-label="Move up" disabled={index === 0} onClick={() => nudge(index, -1)}>↑</button>
            <button type="button" className="btn btn-icon" aria-label="Move down" disabled={index === shown.length - 1} onClick={() => nudge(index, 1)}>↓</button>
          </li>
        );
      })}
    </ul>
  );
}
