import { Server } from "@/components/ui/icons";

import { iconOptions } from "@/features/configuration/emby-server-icon-catalog";

function EmbyServerIcon({
  icon,
  color,
  size = 18,
}: {
  icon?: string;
  color?: string;
  iconStyle?: string;
  size?: number;
}) {
  const Icon = iconOptions.find((option) => option.value === icon)?.Icon || Server;

  return <Icon size={size} style={color ? { color } : undefined} aria-hidden="true" />;
}

export { EmbyServerIcon };
