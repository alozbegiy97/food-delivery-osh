import { type ReactNode, useEffect, useId, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '../../../shared/components/ui';
import type { CategoryOut } from '../../../shared/types/api';

interface CategoryChipsProps {
  categories: CategoryOut[];
  selected: string | null;
  onSelect: (categoryId: string | null) => void;
}

// Category filter chips ("Печь", MA-4.6-B): the selected one is graphite. The
// pair ink-900/cream-50 is the text/background pair that the Telegram theme
// always replaces together with at least 4.5:1 contrast (theme.ts).
const CATEGORY_CHIP =
  'min-h-11 shrink-0 snap-start whitespace-nowrap rounded-full px-[1.125rem] text-[0.9375rem] font-semibold transition-colors';
const CATEGORY_CHIP_SELECTED = 'bg-ink-900 text-cream-50';
const CATEGORY_CHIP_IDLE =
  'bg-surface text-ink-900 ring-1 ring-inset ring-border hover:ring-ink-600';

function CategoryChip({
  selected,
  onClick,
  children,
}: {
  selected: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onClick}
      className={`${CATEGORY_CHIP} ${selected ? CATEGORY_CHIP_SELECTED : CATEGORY_CHIP_IDLE}`}
    >
      {children}
    </button>
  );
}

export function CategoryChips({ categories, selected, onSelect }: CategoryChipsProps) {
  const { t } = useTranslation();

  return (
    <nav
      aria-label={t('menu.categoriesLabel')}
      className="-mx-4 snap-x scroll-px-4 overflow-x-auto px-4 pb-2 pt-1 [scrollbar-width:none]"
    >
      <ul className="flex gap-2">
        <li>
          <CategoryChip selected={selected === null} onClick={() => onSelect(null)}>
            {t('menu.allCategories')}
          </CategoryChip>
        </li>
        {categories.map((category) => (
          <li key={category.id}>
            <CategoryChip selected={selected === category.id} onClick={() => onSelect(category.id)}>
              {category.name}
            </CategoryChip>
          </li>
        ))}
      </ul>
    </nav>
  );
}

interface SearchFieldProps {
  value: string;
  onSearch: (value: string) => void;
}

const SEARCH_DELAY_MS = 350;

/** Search box; the query is applied after a short pause in typing. */
export function SearchField({ value, onSearch }: SearchFieldProps) {
  const { t } = useTranslation();
  const id = useId();
  const [draft, setDraft] = useState(value);
  // When the URL changes from outside (back button, "reset filters"), show
  // the new value; adjusting state during render avoids an extra effect.
  const [shown, setShown] = useState(value);
  if (value !== shown) {
    setShown(value);
    if (draft.trim() !== value) {
      setDraft(value);
    }
  }

  useEffect(() => {
    if (draft.trim() === value) {
      return;
    }
    const timer = window.setTimeout(() => onSearch(draft.trim()), SEARCH_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [draft, value, onSearch]);

  return (
    <form
      role="search"
      onSubmit={(event) => {
        event.preventDefault();
        onSearch(draft.trim());
      }}
      className="relative w-full lg:max-w-[23.75rem]"
    >
      <label htmlFor={id} className="sr-only">
        {t('menu.searchLabel')}
      </label>
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        className="pointer-events-none absolute left-[1.125rem] top-1/2 h-5 w-5 -translate-y-1/2 text-ink-600"
      >
        <circle cx="11" cy="11" r="6.5" fill="none" stroke="currentColor" strokeWidth="1.8" />
        <path d="m20 20-4.2-4.2" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
      <input
        id={id}
        type="search"
        value={draft}
        maxLength={100}
        onChange={(event) => setDraft(event.target.value)}
        placeholder={t('menu.searchPlaceholder')}
        className="min-h-13 w-full rounded-full bg-surface py-2 pl-12 pr-5 text-ink-900 ring-1 ring-inset ring-border transition-shadow placeholder:text-ink-600 hover:ring-ink-600 focus:ring-2 focus:ring-accent-600"
      />
    </form>
  );
}

interface PaginationProps {
  page: number;
  pages: number;
  onPage: (page: number) => void;
}

export function Pagination({ page, pages, onPage }: PaginationProps) {
  const { t } = useTranslation();
  if (pages <= 1) {
    return null;
  }
  // A disabled page button keeps its border on hover (no hover feedback).
  const idleWhenDisabled = 'disabled:hover:ring-border';
  return (
    <nav aria-label={t('menu.paginationLabel')} className="flex items-center justify-center gap-3">
      <Button
        type="button"
        variant="secondary"
        className={idleWhenDisabled}
        disabled={page <= 1}
        onClick={() => onPage(page - 1)}
      >
        {t('menu.previous')}
      </Button>
      <span className="text-sm text-ink-600" aria-live="polite">
        {t('menu.pageOf', { page, pages })}
      </span>
      <Button
        type="button"
        variant="secondary"
        className={idleWhenDisabled}
        disabled={page >= pages}
        onClick={() => onPage(page + 1)}
      >
        {t('menu.next')}
      </Button>
    </nav>
  );
}
