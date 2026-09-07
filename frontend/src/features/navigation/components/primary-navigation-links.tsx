import { GripVertical } from "@/components/ui/icons";
import { useState } from "react";
import { NavLink, useLocation } from "react-router-dom";

import {
  isPrimaryNavigationItemActive,
  primaryNavigation,
} from "@/features/navigation/primary-navigation";
import {
  isSecondaryNavigationItemActive,
  type SecondaryNavigationItem,
} from "@/features/navigation/secondary-navigation";
import { usePersistedTabOrder } from "@/features/navigation/use-persisted-tab-order";
import { cn } from "@/lib/utils";

type NavigationVariant = "sidebar" | "top";

function PrimaryNavigationLinks({
  accountId,
  pathname,
  variant,
  onNavigate,
  showSecondaryMenu = false,
}: {
  accountId?: number | null;
  pathname: string;
  variant: NavigationVariant;
  onNavigate?: () => void;
  showSecondaryMenu?: boolean;
}) {
  const { hash } = useLocation();
  const [openTopSubmenuId, setOpenTopSubmenuId] = useState<string | null>(null);
  const primaryOrder = usePersistedTabOrder({ accountId, page: "primary", tabs: primaryNavigation });
  const orderedPrimaryNavigation = primaryOrder.order
    .map((id) => primaryNavigation.find((item) => item.id === id))
    .filter((item): item is (typeof primaryNavigation)[number] => Boolean(item));

  return (
    <nav aria-label="Navigazione principale" className={`app-navigation app-navigation--${variant}`}>
      {orderedPrimaryNavigation.map((item) => {
        const Icon = item.icon;
        const active = isPrimaryNavigationItemActive(item, pathname);
        const hasSecondaryMenu = showSecondaryMenu && Boolean(item.secondary?.length);
        const topSubmenuOpen = variant === "top" && openTopSubmenuId === item.id;
        const showItemSubmenu = hasSecondaryMenu && (variant === "sidebar" ? active : topSubmenuOpen);

        function closeTopSubmenu() {
          if (variant === "top") setOpenTopSubmenuId(null);
        }

        return (
          <div
            className="navigation-item"
            key={item.to}
            onMouseEnter={variant === "top" && hasSecondaryMenu ? () => setOpenTopSubmenuId(item.id) : undefined}
            onMouseLeave={variant === "top" && hasSecondaryMenu ? closeTopSubmenu : undefined}
            onFocusCapture={variant === "top" && hasSecondaryMenu ? () => setOpenTopSubmenuId(item.id) : undefined}
            onBlurCapture={variant === "top" && hasSecondaryMenu ? (event) => {
              const nextFocused = event.relatedTarget;
              if (!(nextFocused instanceof Node) || !event.currentTarget.contains(nextFocused)) closeTopSubmenu();
            } : undefined}
            onKeyDown={variant === "top" && hasSecondaryMenu ? (event) => {
              if (event.key === "Escape") {
                event.preventDefault();
                closeTopSubmenu();
              }
            } : undefined}
          >
            <NavLink
              to={item.to}
              data-primary-navigation-id={item.id}
              onClick={() => {
                closeTopSubmenu();
                onNavigate?.();
              }}
              aria-current={active ? "page" : undefined}
              aria-expanded={variant === "top" && hasSecondaryMenu ? topSubmenuOpen : undefined}
              aria-haspopup={variant === "top" && hasSecondaryMenu ? "true" : undefined}
              className={cn("navigation-link", `navigation-link--${variant}`, active && "is-active", primaryOrder.draggingId === item.id && "is-dragging")}
              title="Trascina per riordinare"
              {...primaryOrder.interaction(item.id, { dropAxis: variant === "sidebar" ? "vertical" : "horizontal" })}
            >
              <Icon size={variant === "sidebar" ? 17 : 16} strokeWidth={2} aria-hidden="true" />
              <span>{item.label}</span>
              <GripVertical className="navigation-reorder-grip" size={12} aria-hidden="true" />
            </NavLink>
            {showItemSubmenu && item.secondary?.length ? (
              <SecondaryNavigationMenu
                accountId={accountId}
                hash={hash}
                items={item.secondary}
                onNavigate={() => {
                  closeTopSubmenu();
                  onNavigate?.();
                }}
                orderPage={item.secondaryOrderPage || item.id}
                pathname={pathname}
                primaryLabel={item.label}
                variant={variant}
              />
            ) : null}
          </div>
        );
      })}
      <span className="sr-only" aria-live="polite">{primaryOrder.announcement}</span>
    </nav>
  );
}

function SecondaryNavigationMenu({
  accountId,
  hash,
  items,
  onNavigate,
  orderPage,
  pathname,
  primaryLabel,
  variant,
}: {
  accountId?: number | null;
  hash: string;
  items: readonly SecondaryNavigationItem[];
  onNavigate?: () => void;
  orderPage: string;
  pathname: string;
  primaryLabel: string;
  variant: NavigationVariant;
}) {
  const submenuOrder = usePersistedTabOrder({ accountId, page: orderPage, tabs: items });
  const orderedItems = submenuOrder.order
    .map((id) => items.find((item) => item.id === id))
    .filter((item): item is SecondaryNavigationItem => Boolean(item));

  return (
    <div className={`navigation-submenu navigation-submenu--${variant}`} aria-label={`Sezioni ${primaryLabel}`}>
      {orderedItems.map((item) => {
        const active = isSecondaryNavigationItemActive(item, pathname, hash);
        return (
          <NavLink
            key={item.to}
            to={item.to}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={cn("navigation-submenu-link", active && "is-active", submenuOrder.draggingId === item.id && "is-dragging")}
            title="Trascina per riordinare"
            {...submenuOrder.interaction(item.id, { dropAxis: variant === "sidebar" ? "vertical" : "horizontal" })}
          >
            {item.label}
            <GripVertical className="navigation-reorder-grip" size={11} aria-hidden="true" />
          </NavLink>
        );
      })}
      <span className="sr-only" aria-live="polite">{submenuOrder.announcement}</span>
    </div>
  );
}

export { PrimaryNavigationLinks };
