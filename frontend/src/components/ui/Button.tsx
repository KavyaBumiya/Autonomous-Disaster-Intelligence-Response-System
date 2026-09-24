import React from "react";

type Variant = "default" | "primary" | "danger" | "ghost";

const variantClass: Record<Variant, string> = {
  default: "ops-button",
  primary: "ops-button ops-button-primary",
  danger: "ops-button ops-button-danger",
  ghost: "ops-button ops-button-ghost",
};

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: "sm" | "md";
  block?: boolean;
}

export const Button: React.FC<ButtonProps> = ({
  variant = "default",
  size = "md",
  block = false,
  className = "",
  children,
  ...rest
}) => (
  <button
    type="button"
    className={[
      variantClass[variant],
      size === "sm" ? "ops-button-sm" : "",
      block ? "w-full" : "",
      className,
    ]
      .filter(Boolean)
      .join(" ")}
    {...rest}
  >
    {children}
  </button>
);
