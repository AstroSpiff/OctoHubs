import { Slot } from "@radix-ui/react-slot";
import type { VariantProps } from "class-variance-authority";
import { forwardRef } from "react";
import type { ButtonHTMLAttributes } from "react";

import { buttonVariants } from "@/components/ui/button-variants";
import { useWorkspaceCapabilities } from "@/features/session/workspace-capabilities-context";
import { cn } from "@/lib/utils";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
    requiresWriteAccess?: boolean;
  };

const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant, size, asChild = false, requiresWriteAccess = false, ...props },
  ref,
) {
  const { canMutate } = useWorkspaceCapabilities();
  if (requiresWriteAccess && !canMutate) return null;

  const Component = asChild ? Slot : "button";
  return <Component ref={ref} className={cn(buttonVariants({ variant, size }), className)} {...props} />;
});

Button.displayName = "Button";

export { Button };
