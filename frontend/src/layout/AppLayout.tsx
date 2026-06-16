import { AppShell, Burger, Group, NavLink, Text, Button } from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { Outlet, useLocation, useNavigate, Link } from 'react-router-dom';
import {
  IconDashboard,
  IconBuildingWarehouse,
  IconPackages,
  IconCurrencyDollar,
  IconTable,
  IconCategory,
  IconTag,
  IconListDetails,
  IconBook,
  IconNews,
} from '@tabler/icons-react';
import type { Icon as TablerIcon } from '@tabler/icons-react';
import { useAuth } from '@/auth/AuthContext';

interface NavItem {
  to: string;
  label: string;
  icon: TablerIcon;
  /** Sub-routes rendered as nested NavLinks. */
  children?: NavItem[];
}

const NAV_ITEMS: NavItem[] = [
  { to: '/', label: 'Главная', icon: IconDashboard },
  { to: '/suppliers', label: 'Поставщики', icon: IconBuildingWarehouse },
  { to: '/products', label: 'Продукты', icon: IconPackages },
  // Reference data behind the product catalog — own group so the Products
  // link stays a single-click destination instead of an expandable parent.
  // `to` here is just the first child's URL: clicking the group navigates
  // to Categories (a reasonable default landing) and keeps the section
  // expanded via `isActive` while the user is on any of the children.
  {
    to: '/products/categories',
    label: 'Справочники',
    icon: IconBook,
    children: [
      { to: '/products/categories', label: 'Категории', icon: IconCategory },
      { to: '/products/brands', label: 'Бренды', icon: IconTag },
      { to: '/products/characteristics', label: 'Характеристики', icon: IconListDetails },
    ],
  },
  { to: '/prices', label: 'Цены', icon: IconCurrencyDollar },
  { to: '/dataframe', label: 'Dataframe', icon: IconTable },
  { to: '/articles', label: 'Статьи', icon: IconNews },
];

/**
 * Active-state resolution by longest path prefix. With "Продукты" (`/products`)
 * and "Справочники" sharing the `/products` prefix, plain `startsWith` would
 * light up both at once. We pick the item whose URL is the *longest* prefix
 * of the current path — so `/products/categories` highlights Справочники,
 * while `/products/123` (or the bare list) highlights Продукты.
 */
function flattenPaths(items: NavItem[]): string[] {
  const out: string[] = [];
  for (const i of items) {
    out.push(i.to);
    if (i.children) out.push(...flattenPaths(i.children));
  }
  return out;
}

function pickActivePath(items: NavItem[], currentPath: string): string | null {
  let best: string | null = null;
  for (const path of flattenPaths(items)) {
    if (path === '/') {
      if (currentPath === '/' && (best === null || path.length > best.length)) {
        best = path;
      }
      continue;
    }
    if (currentPath === path || currentPath.startsWith(path + '/')) {
      if (best === null || path.length > best.length) best = path;
    }
  }
  return best;
}

/**
 * An item is active when:
 *  - it directly owns the winning path, OR
 *  - it has children, and one of them owns the winning path (so the
 *    parent group stays highlighted while a child is selected).
 */
function isItemActive(item: NavItem, activePath: string | null): boolean {
  if (!activePath) return false;
  if (item.to === activePath) return true;
  if (item.children?.some((c) => c.to === activePath)) return true;
  return false;
}

export function AppLayout() {
  const [opened, { toggle }] = useDisclosure();
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuth();

  async function handleLogout() {
    await logout();
    navigate('/login');
  }

  return (
    <AppShell
      header={{ height: 56 }}
      navbar={{ width: 240, breakpoint: 'sm', collapsed: { mobile: !opened } }}
      padding="md"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group>
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" />
            <Text fw={700} size="lg">
              Price Manager
            </Text>
          </Group>
          <Group>
            {user && <Text size="sm">{user.username}</Text>}
            <Button size="xs" variant="subtle" onClick={handleLogout}>
              Выйти
            </Button>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="xs">
        {(() => {
          const activePath = pickActivePath(NAV_ITEMS, location.pathname);
          return NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const active = isItemActive(item, activePath);
            return (
              <NavLink
                key={item.label}
                component={Link}
                to={item.to}
                label={item.label}
                leftSection={<Icon size={18} />}
                active={active}
                defaultOpened={!!item.children && active}
                childrenOffset={28}
              >
                {item.children?.map((child) => {
                  const ChildIcon = child.icon;
                  return (
                    <NavLink
                      key={child.to}
                      component={Link}
                      to={child.to}
                      label={child.label}
                      leftSection={<ChildIcon size={16} />}
                      active={activePath === child.to}
                    />
                  );
                })}
              </NavLink>
            );
          });
        })()}
      </AppShell.Navbar>

      <AppShell.Main>
        <Outlet />
      </AppShell.Main>
    </AppShell>
  );
}
