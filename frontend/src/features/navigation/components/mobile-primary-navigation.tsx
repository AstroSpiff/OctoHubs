import { X } from "@/components/ui/icons";
import { useEffect, useRef, useState, type CSSProperties } from "react";
import { NavLink, useLocation } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { DialogBackdrop } from "@/components/ui/dialog-backdrop";
import {
  isPrimaryNavigationItemActive,
  primaryNavigation,
  type PrimaryNavigationItem,
} from "@/features/navigation/primary-navigation";
import {
  isSecondaryNavigationItemActive,
  type SecondaryNavigationItem,
} from "@/features/navigation/secondary-navigation";
import {
  usePersistedTabOrder,
  type TabOrderInteraction,
} from "@/features/navigation/use-persisted-tab-order";
import { cn } from "@/lib/utils";

const longPressDelay = 480;

function MobilePrimaryNavigation({ pathname }: { pathname: string }) {
  const { hash } = useLocation();
  const pressTimer = useRef<number | null>(null);
  const suppressClickFor = useRef<string | null>(null);
  const [secondaryMenu, setSecondaryMenu] = useState<PrimaryNavigationItem | null>(null);
  const primaryOrder = usePersistedTabOrder({ page: "primary", tabs: primaryNavigation });
  const orderedPrimaryNavigation = primaryOrder.order
    .map((id) => primaryNavigation.find((item) => item.id === id))
    .filter((item): item is (typeof primaryNavigation)[number] => Boolean(item));

  useEffect(() => () => {
    if (pressTimer.current !== null) window.clearTimeout(pressTimer.current);
  }, []);

  function clearLongPress() {
    if (pressTimer.current === null) return;
    window.clearTimeout(pressTimer.current);
    pressTimer.current = null;
  }

  function beginLongPress(item: PrimaryNavigationItem) {
    if (!item.secondary?.length) return;
    clearLongPress();
    pressTimer.current = window.setTimeout(() => {
      suppressClickFor.current = item.to;
      setSecondaryMenu(item);
      pressTimer.current = null;
    }, longPressDelay);
  }

  return (
    <>
      <nav
        className="mobile-primary-navigation"
        aria-label="Navigazione principale mobile"
        style={{ "--mobile-primary-navigation-count": orderedPrimaryNavigation.length } as CSSProperties}
      >
        {orderedPrimaryNavigation.map((item) => {
          const Icon = item.icon;
          const active = isPrimaryNavigationItemActive(item, pathname);
          const orderInteraction = primaryOrder.interaction(item.id);
          return (
            <NavLink
              key={item.to}
              to={item.to}
              className={cn("mobile-navigation-link", active && "is-active", primaryOrder.draggingId === item.id && "is-dragging")}
              onPointerDown={() => beginLongPress(item)}
              onPointerUp={clearLongPress}
              onPointerCancel={clearLongPress}
              onPointerLeave={clearLongPress}
              onContextMenu={(event) => {
                if (!item.secondary?.length) return;
                event.preventDefault();
                suppressClickFor.current = item.to;
                setSecondaryMenu(item);
              }}
              onClick={(event) => {
                if (suppressClickFor.current !== item.to) return;
                event.preventDefault();
                suppressClickFor.current = null;
              }}
              title="Trascina per riordinare"
              {...orderInteraction}
              onDragStart={(event) => {
                clearLongPress();
                orderInteraction.onDragStart(event);
              }}
            >
              <Icon size={20} strokeWidth={active ? 2.4 : 2} aria-hidden="true" />
              <span>{item.shortLabel}</span>
            </NavLink>
          );
        })}
      </nav>
      {secondaryMenu?.secondary ? (
        <SecondaryNavigationSheet
          hash={hash}
          item={secondaryMenu}
          pathname={pathname}
          onClose={() => setSecondaryMenu(null)}
        />
      ) : null}
    </>
  );
}

function SecondaryNavigationSheet({
  hash,
  item,
  onClose,
  pathname,
}: {
  hash: string;
  item: PrimaryNavigationItem;
  onClose: () => void;
  pathname: string;
}) {
  const submenuOrder = usePersistedTabOrder({
    page: item.secondaryOrderPage || item.id,
    tabs: item.secondary || [],
  });
  const orderedItems = submenuOrder.order
    .map((id) => item.secondary?.find((secondary) => secondary.id === id))
    .filter((secondary): secondary is SecondaryNavigationItem => Boolean(secondary));

  return (
    <DialogBackdrop className="mobile-secondary-navigation-backdrop" onDismiss={onClose}>
      <section className="mobile-secondary-navigation-sheet" role="dialog" aria-modal="true" aria-labelledby="mobile-secondary-navigation-title">
        <header>
          <div>
            <h2 id="mobile-secondary-navigation-title" className="contextual-heading" title="Accesso diretto">{item.label}</h2>
          </div>
          <Button type="button" variant="ghost" size="icon" onClick={onClose} aria-label="Chiudi menu secondario" title="Chiudi">
            <X size={18} aria-hidden="true" />
          </Button>
        </header>
        <nav aria-label={`Sezioni ${item.label}`}>
          {orderedItems.map((secondary) => (
            <SecondaryNavigationLink
              key={secondary.to}
              active={isSecondaryNavigationItemActive(secondary, pathname, hash)}
              item={secondary}
              onNavigate={onClose}
              interaction={submenuOrder.interaction(secondary.id, { dropAxis: "vertical" })}
            />
          ))}
        </nav>
      </section>
    </DialogBackdrop>
  );
}

function SecondaryNavigationLink({
  active,
  interaction,
  item,
  onNavigate,
}: {
  active: boolean;
  interaction: TabOrderInteraction;
  item: SecondaryNavigationItem;
  onNavigate: () => void;
}) {
  return (
    <NavLink
      to={item.to}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cn("mobile-secondary-navigation-link", active && "is-active")}
      title="Trascina per riordinare"
      {...interaction}
    >
      {item.label}
    </NavLink>
  );
}

export { MobilePrimaryNavigation };
