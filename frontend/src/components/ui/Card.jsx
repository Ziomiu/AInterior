export default function Card({ children, className = "", ...props }) {
  return (
    <div
      className={`rounded-lg border border-foreground/10 bg-white shadow-sm ${className}`}
      {...props}
    >
      {children}
    </div>
  );
}
