import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Search, X } from "lucide-react";
import { useCaseSearch } from "../../api/hooks";
import { errorMessage } from "../../api/client";
import type { SearchResult } from "../../types/api";
import { STATUS_LABELS_FALLBACK } from "../../lib/labels";

export const SEARCH_DEBOUNCE_MS = 250;
export const SEARCH_MIN_CHARS = 2;

const MATCH_LABEL: Record<string, (r: SearchResult) => string> = {
  case: () => "case ID",
  transaction: (r) => `transaction ${r.disputed_txn_id}`,
  reference: () => "payment reference (UTR)",
  customer: () => "customer ID",
  account: () => "account on the disputed payment",
};
export const matchedOnLabel = (r: SearchResult) => (MATCH_LABEL[r.matched_on] ?? (() => r.matched_on))(r);

function useDebounced(value: string, ms: number): string {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(t);
  }, [value, ms]);
  return v;
}

function isTypingTarget(t: EventTarget | null): boolean {
  if (!(t instanceof HTMLElement)) return false;
  return t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName);
}

/** Top-bar case search: combobox + listbox, debounced, "/" to focus. Collapses to an icon on narrow screens. */
export default function GlobalSearch() {
  const nav = useNavigate();
  const [value, setValue] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [expanded, setExpanded] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const listId = useId();
  const optId = (i: number) => `${listId}-opt-${i}`;

  const term = useDebounced(value.trim(), SEARCH_DEBOUNCE_MS);
  const enough = term.length >= SEARCH_MIN_CHARS;
  const q = useCaseSearch(enough ? term : "");
  const results = enough && q.data && q.data.query === term ? q.data.results : [];
  const pending = value.trim() !== term || (enough && q.isFetching && !q.data);

  useEffect(() => setActive(-1), [term]);

  // "/" focuses search from anywhere that isn't a text field.
  useEffect(() => {
    const h = (e: globalThis.KeyboardEvent) => {
      if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey || isTypingTarget(e.target)) return;
      e.preventDefault();
      setExpanded(true);
      window.setTimeout(() => inputRef.current?.focus(), 0);
    };
    document.addEventListener("keydown", h);
    return () => document.removeEventListener("keydown", h);
  }, []);

  // Close when focus or a click leaves the widget.
  useEffect(() => {
    if (!open && !expanded) return;
    const h = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
        setExpanded(false);
      }
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open, expanded]);

  const go = (r: SearchResult) => {
    setOpen(false);
    setExpanded(false);
    setValue("");
    inputRef.current?.blur();
    nav(`/cases/${encodeURIComponent(r.id)}`);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      if (results.length) setActive((i) => (i + 1) % results.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setOpen(true);
      if (results.length) setActive((i) => (i <= 0 ? results.length - 1 : i - 1));
    } else if (e.key === "Enter") {
      const r = results[active >= 0 ? active : 0];
      if (r && !pending) {
        e.preventDefault();
        go(r);
      }
    } else if (e.key === "Escape") {
      e.preventDefault();
      if (open && value) setOpen(false);
      else {
        setValue("");
        setOpen(false);
        setExpanded(false);
        inputRef.current?.blur();
      }
    } else if (e.key === "Home" && open && results.length) {
      setActive(0);
    } else if (e.key === "End" && open && results.length) {
      setActive(results.length - 1);
    }
  };

  const showList = open && value.trim().length > 0;
  let status: string | null = null;
  if (showList) {
    if (value.trim().length < SEARCH_MIN_CHARS) status = `Type at least ${SEARCH_MIN_CHARS} characters`;
    else if (pending) status = "Searching…";
    else if (q.error) status = errorMessage(q.error);
    else if (!results.length) status = `No cases match “${term}”`;
  }

  return (
    <div ref={wrapRef} className={`gsearch ${expanded ? "is-expanded" : ""}`}>
      <button
        type="button"
        className="icon-btn gsearch-open"
        aria-label="Search cases"
        aria-expanded={expanded}
        onClick={() => {
          setExpanded(true);
          window.setTimeout(() => inputRef.current?.focus(), 0);
        }}
      >
        <Search size={18} />
      </button>
      <div className="gsearch-field">
        <Search size={15} className="gsearch-icon" aria-hidden="true" />
        <input
          ref={inputRef}
          className="input gsearch-input"
          type="text"
          role="combobox"
          aria-label="Search cases"
          aria-autocomplete="list"
          aria-expanded={showList && results.length > 0}
          aria-controls={listId}
          aria-activedescendant={showList && active >= 0 && results[active] ? optId(active) : undefined}
          placeholder="Search case, transaction, UTR, account…"
          autoComplete="off"
          spellCheck={false}
          maxLength={64}
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
        />
        {value ? (
          <button
            type="button"
            className="icon-btn icon-btn-sm gsearch-clear"
            aria-label="Clear search"
            onClick={() => {
              setValue("");
              inputRef.current?.focus();
            }}
          >
            <X size={14} />
          </button>
        ) : (
          <kbd className="gsearch-kbd" aria-hidden="true">
            /
          </kbd>
        )}
        <div className={`gsearch-pop ${showList ? "is-open" : ""}`}>
          <ul id={listId} role="listbox" aria-label="Matching cases" className="gsearch-list" hidden={!showList || results.length === 0}>
            {results.map((r, i) => (
              <li
                key={r.id}
                id={optId(i)}
                role="option"
                aria-selected={i === active}
                className={`gsearch-opt ${i === active ? "is-active" : ""}`}
                onMouseDown={(e) => e.preventDefault()}
                onMouseMove={() => setActive(i)}
                onClick={() => go(r)}
              >
                <span className="gsearch-opt-top">
                  <span className={`chip chip-sm prio prio-${r.priority}`}>{r.priority}</span>
                  <span className="gsearch-id num">{r.id}</span>
                  <span className="gsearch-amount num">{r.amount_label}</span>
                </span>
                <span className="gsearch-opt-sub">
                  {r.category_label} · {STATUS_LABELS_FALLBACK[r.status] ?? r.status}
                </span>
                <span className="gsearch-opt-match">Matched on {matchedOnLabel(r)}</span>
              </li>
            ))}
          </ul>
          <p className={`gsearch-status ${status ? "" : "sr-only"}`} role="status" aria-live="polite">
            {status ?? (showList ? `${results.length} matching ${results.length === 1 ? "case" : "cases"}` : "")}
          </p>
        </div>
      </div>
    </div>
  );
}
