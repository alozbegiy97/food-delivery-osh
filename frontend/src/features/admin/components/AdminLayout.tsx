import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Navigate, NavLink, Outlet, useLocation } from 'react-router';

import { useMeQuery } from '../../auth/authApi';

export type StaffRole = 'admin' | 'cook' | 'courier';

/**
 * Allows only users with one of `roles` (DEC-23, DEC-150). This is a
 * convenience for the interface: every API checks the roles again.
 */
export function RequireStaff({ roles, children }: { roles: StaffRole[]; children: ReactNode }) {
  const { t } = useTranslation();
  const { data, isLoading } = useMeQuery();
  if (isLoading) {
    return (
      <p role="status" className="text-ink-600">
        {t('auth.checkingSession')}
      </p>
    );
  }
  if (!data?.roles.some((role) => (roles as string[]).includes(role))) {
    return (
      <section className="mx-auto max-w-md rounded-card border border-border bg-surface p-6 text-center">
        <h1 className="text-xl font-bold">{t('admin.forbiddenTitle')}</h1>
        <p className="mt-2 text-ink-600">{t('admin.forbiddenText')}</p>
      </section>
    );
  }
  return children;
}

/** Kept for the catalog routes of stage 4B. */
export function RequireAdmin({ children }: { children: ReactNode }) {
  return <RequireStaff roles={['admin']}>{children}</RequireStaff>;
}

/** `/admin` index: administrators land on the dashboard, cooks on the kitchen. */
export function StaffHome() {
  const { data } = useMeQuery();
  return <Navigate to={data?.roles.includes('admin') ? 'dashboard' : 'kitchen'} replace />;
}

interface Section {
  to: string;
  key: string;
  roles: StaffRole[];
}

const GROUPS: { key: string; sections: Section[] }[] = [
  {
    key: 'workGroup',
    sections: [
      { to: '/admin/dashboard', key: 'dashboard', roles: ['admin'] },
      { to: '/admin/orders', key: 'orders', roles: ['admin'] },
      { to: '/admin/cancellations', key: 'cancellations', roles: ['admin'] },
      { to: '/admin/kitchen', key: 'kitchen', roles: ['admin', 'cook'] },
      { to: '/admin/couriers', key: 'couriers', roles: ['admin'] },
    ],
  },
  {
    key: 'catalogGroup',
    sections: [
      { to: '/admin/categories', key: 'categories', roles: ['admin'] },
      { to: '/admin/products', key: 'products', roles: ['admin'] },
      { to: '/admin/modifiers', key: 'modifiers', roles: ['admin'] },
    ],
  },
  {
    key: 'restaurantGroup',
    sections: [
      { to: '/admin/staff', key: 'staff', roles: ['admin'] },
      { to: '/admin/zones', key: 'zones', roles: ['admin'] },
      { to: '/admin/settings', key: 'settings', roles: ['admin'] },
    ],
  },
];

/**
 * Staff frame (DEC-77, UI_UX_GUIDELINES §4): sidebar on desktop, drawer on
 * phones; the sections depend on the roles (the cook sees only the kitchen).
 */
export function AdminLayout() {
  const { t } = useTranslation();
  const location = useLocation();
  const { data } = useMeQuery();
  const [openOn, setOpenOn] = useState<string | null>(null);
  const open = openOn === location.pathname;
  const roles = data?.roles ?? [];
  const visible = GROUPS.map((group) => ({
    ...group,
    sections: group.sections.filter((s) => s.roles.some((role) => roles.includes(role))),
  })).filter((group) => group.sections.length > 0);

  const nav = (
    <nav aria-label={t('admin.navLabel')} className="flex flex-col gap-4">
      {visible.map((group) => (
        <div key={group.key} className="flex flex-col gap-1">
          <p className="px-3 pb-1 text-xs font-semibold uppercase tracking-wide text-ink-600">
            {t(`admin.${group.key}`)}
          </p>
          {group.sections.map((section) => (
            <NavLink
              key={section.key}
              to={section.to}
              className={({ isActive }) =>
                [
                  'rounded-xl px-3 py-2.5 text-sm font-semibold transition',
                  isActive ? 'bg-accent-50 text-accent-800' : 'text-ink-900 hover:bg-cream-100',
                ].join(' ')
              }
            >
              {t(`admin.sections.${section.key}`)}
            </NavLink>
          ))}
        </div>
      ))}
    </nav>
  );

  return (
    <div className="flex flex-col gap-6 lg:flex-row">
      <aside className="lg:w-56 lg:shrink-0">
        <div className="flex items-center justify-between lg:block">
          <p className="text-lg font-extrabold">{t('admin.title')}</p>
          <button
            type="button"
            className="min-h-11 rounded-full px-4 text-sm font-semibold ring-1 ring-border lg:hidden"
            aria-expanded={open}
            aria-controls="admin-nav"
            onClick={() => setOpenOn(open ? null : location.pathname)}
          >
            {t('admin.sectionsButton')}
          </button>
        </div>
        <div
          id="admin-nav"
          className={`${open ? 'block' : 'hidden'} mt-3 lg:sticky lg:top-24 lg:block`}
        >
          {nav}
        </div>
      </aside>
      <div className="min-w-0 flex-1">
        <Outlet />
      </div>
    </div>
  );
}
