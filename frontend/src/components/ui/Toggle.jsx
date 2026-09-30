export default function Toggle({ checked, onChange, className = "" }) {
  return (
    <div
      onClick={() => onChange(!checked)}
      className={`w-12 h-6 flex items-center rounded-full p-1 cursor-pointer transition-colors duration-200 ${checked ? "bg-accent" : "bg-foreground/20"} ${className}`}
    >
      <div
        className={`bg-white w-5 h-5 rounded-full shadow-md transform transition-transform duration-200 ${checked ? "translate-x-6" : "translate-x-0"}`}
      />
    </div>
  );
}
