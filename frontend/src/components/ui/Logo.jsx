import LogoIcon from "../../assets/logo.png";

export default function Logo({ className = "" }) {
  return (
    <img
      src={LogoIcon}
      alt="AInterior"
      className={`h-12 md:h-16 w-auto object-contain ${className}`}
    />
  );
}
