import { Link } from "react-router-dom";
import type { LinkProps } from "react-router-dom";
import { buttonClasses } from "@/shared/components/Button";
import type { ButtonSize, ButtonVariant } from "@/shared/components/Button";

interface LinkButtonProps extends LinkProps {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

/** Router <Link> styled identically to <Button> — see buttonClasses(). Use
 * this instead of nesting a <Link> inside a <Button> (no asChild/Slot
 * pattern in this app, kept deliberately dependency-light). */
export function LinkButton({ variant = "ghost", size = "default", className, ...rest }: LinkButtonProps) {
  return <Link className={buttonClasses(variant, size, className)} {...rest} />;
}
