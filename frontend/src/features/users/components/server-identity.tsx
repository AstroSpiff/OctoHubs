import { EmbyServerIcon } from "@/features/emby-live/components/emby-server-icon";

type ServerIdentityProps = {
  name: string;
  icon?: string;
  color?: string;
  iconStyle?: string;
  size?: number;
  className?: string;
};

function ServerIdentity({
  name,
  icon,
  color,
  iconStyle,
  size = 14,
  className,
}: ServerIdentityProps) {
  return (
    <span className={`users-server-identity${className ? ` ${className}` : ""}`}>
      <EmbyServerIcon
        icon={icon}
        color={color}
        iconStyle={iconStyle}
        size={size}
      />
      <span title={name}>{name}</span>
    </span>
  );
}

export { ServerIdentity };
