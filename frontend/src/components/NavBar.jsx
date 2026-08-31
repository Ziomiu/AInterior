import { useSelector } from "react-redux";
import { Link as RouterLink } from "react-router-dom";

import Logo from "./ui/Logo";
import Button from "./ui/Button";
import { useAuthModal } from "../context/AuthModalContext";

const baseLinks = [
  { href: "/views/workflows", label: "Workflows" },
  { href: "/views/prompts", label: "Prompts" },
  { href: "/views/gallery", label: "Gallery" },
];

export default function Navbar() {
  const { isAuthenticated, user } = useSelector((state) => state.auth);
  const { openLogin } = useAuthModal();

  const navLinks = [...baseLinks];
  if (isAuthenticated && user?.role === "admin") {
    navLinks.push({ href: "/views/adminPanel", label: "Admin Panel" });
  }

  return (
    <nav className="bg-background text-foreground px-5 py-3 border-b border-foreground/10 shadow-sm">
      <div className="flex items-center justify-between gap-8">
        <RouterLink to="/views/landing" className="flex-shrink-0">
          <Logo />
        </RouterLink>

        <div className="flex flex-wrap items-center gap-10">
          <div className="flex flex-wrap items-center gap-8">
            {navLinks.map(({ href, label }) => (
              <RouterLink
                key={href}
                to={href}
                className="text-muted hover:text-foreground no-underline font-sans text-sm uppercase tracking-wider transition-colors"
              >
                {label}
              </RouterLink>
            ))}
          </div>

          <div className="flex items-center gap-6">
            {isAuthenticated && (
              <RouterLink
                to="/views/account/logout"
                className="text-muted hover:text-foreground no-underline font-sans text-sm uppercase tracking-wider transition-colors"
              >
                Logout
              </RouterLink>
            )}

            {isAuthenticated ? (
              <RouterLink to="/views/workflows">
                <Button icon="+">New Project</Button>
              </RouterLink>
            ) : (
              <Button icon="+" onClick={openLogin}>
                New Project
              </Button>
            )}
          </div>
        </div>
      </div>
    </nav>
  );
}