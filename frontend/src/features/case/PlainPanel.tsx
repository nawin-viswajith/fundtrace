import type { ReactNode } from "react";

/** A card whose title is an h2, so the case Overview reads h1 (case) → h2 (section) → h3 (detail). */
export function PlainPanel({
  id,
  title,
  subtitle,
  actions,
  className = "",
  children,
}: {
  id: string;
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
  className?: string;
  children?: ReactNode;
}) {
  const hid = `${id}-title`;
  return (
    <section className={`card plain-panel ${className}`} id={id} aria-labelledby={hid}>
      <header className="card-head">
        <div className="card-titles">
          <h2 id={hid} className="card-title plain-panel-title" tabIndex={-1}>
            {title}
          </h2>
          {subtitle && <p className="card-subtitle plain-panel-sub">{subtitle}</p>}
        </div>
        {actions && <div className="card-actions">{actions}</div>}
      </header>
      {children}
    </section>
  );
}
