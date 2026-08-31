export default function Input({ className = "", ...props }) {
  return (
    <input
      className={`w-full rounded-md border border-foreground/15 bg-transparent px-4 py-2.5 text-sm text-foreground/85 placeholder:text-muted/50 focus:outline-none focus:ring-2 focus:ring-accent disabled:opacity-50 disabled:cursor-not-allowed ${className}`}
      {...props}
    />
  );
}
