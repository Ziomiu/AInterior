import React from "react";

const sizes = {
  md: "px-[clamp(1rem,0.8rem+0.8vw,1.5rem)] py-[clamp(0.5rem,0.4rem+0.4vw,0.75rem)] text-[clamp(0.7rem,0.65rem+0.3vw,0.875rem)]",
  lg: "px-[clamp(1.25rem,0.9rem+1.4vw,2rem)] py-[clamp(0.65rem,0.5rem+0.6vw,1rem)] text-[clamp(0.75rem,0.68rem+0.4vw,1rem)]",
};

export default function Button({
  children,
  icon,
  size = "md",
  className = "",
  ...props
}) {
  return (
    <button
      type="button"
      className={`inline-flex items-center gap-2 rounded-sm bg-primary text-primary-foreground font-sans font-medium uppercase tracking-wider shadow-sm hover:opacity-90 transition-opacity cursor-pointer ${sizes[size]} ${className}`}
      {...props}
    >
      {icon && <span aria-hidden="true">{icon}</span>}
      {children}
    </button>
  );
}
