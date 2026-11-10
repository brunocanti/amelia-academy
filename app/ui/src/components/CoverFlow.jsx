import { useEffect, useRef } from 'react';
import './coverflow.css';

/** Cover Flow: the selected picture faces forward; the ones beside it turn away, as album covers did in iTunes. */
export function CoverFlow({ items, selectedId, onSelect, label = 'Figures' }) {
  const host = useRef(null);
  const index = Math.max(0, items.findIndex((item) => item.id === selectedId));

  useEffect(() => {
    function onKey(event) {
      if (!host.current?.contains(document.activeElement) && document.activeElement !== host.current) return;
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
      event.preventDefault();
      const next = index + (event.key === 'ArrowRight' ? 1 : -1);
      if (items[next]) onSelect?.(items[next].id);
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [index, items, onSelect]);

  if (!items.length) return null;

  return (
    <div className="coverflow" ref={host} tabIndex={0} role="listbox" aria-label={label} aria-activedescendant={items[index]?.id}>
      <div className="coverflow-stage">
        {items.map((item, i) => {
          const offset = i - index;
          const side = offset === 0 ? 0 : Math.sign(offset);
          return (
            <button
              key={item.id}
              id={item.id}
              type="button"
              role="option"
              aria-selected={offset === 0}
              title={item.alt || 'Show this one'}
              className={`cover${offset === 0 ? ' is-selected' : ''}${item.flag ? ' is-flagged' : ''}`}
              style={{
                left: `calc(50% + ${offset} * var(--cover-step))`,
                transform: `translateX(-50%) translateZ(${offset === 0 ? 48 : -70}px) rotateY(${side * -58}deg)`,
                zIndex: 30 - Math.abs(offset),
              }}
              onClick={() => onSelect?.(item.id)}
            >
              {item.url
                ? <img src={item.url} alt={item.alt || ''} draggable="false" />
                : <span className="cover-missing">No preview</span>}
              {item.flag && <span className="cover-flag">{item.flag}</span>}
            </button>
          );
        })}
      </div>
    </div>
  );
}
