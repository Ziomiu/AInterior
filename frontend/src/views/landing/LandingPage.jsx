import { useEffect } from "react";
import { useSelector } from "react-redux";
import { useLocation, useNavigate } from "react-router-dom";

import Button from "../../components/ui/Button";
import HeroBackground from "../../assets/background.jpg";
import { useAuthModal } from "../../context/AuthModalContext";

export default function LandingPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const isAuthenticated = useSelector((state) => state.auth.isAuthenticated);
  const { openLogin, openRegister } = useAuthModal();

  useEffect(() => {
    const authModal = location.state?.authModal;
    if (!authModal) return;

    if (authModal === "register") openRegister();
    else openLogin();

    navigate(location.pathname, { replace: true, state: null });
  }, [location, navigate, openLogin, openRegister]);

  const handleStartCreating = () => {
    if (isAuthenticated) navigate("/views/workflows/text-to-image");
    else openLogin();
  };

  return (
    <section
      className="relative flex-1 flex items-center bg-cover bg-center"
      style={{ backgroundImage: `url(${HeroBackground})` }}
    >
      <div className="max-w-xl px-[clamp(1.25rem,1rem+3vw,5rem)]">
        <h1 className="font-serif text-[clamp(1.75rem,1.2rem+2.8vw,3.75rem)] leading-tight text-foreground mb-4 sm:mb-6">
          Design spaces that feel inviting.
        </h1>

        <p className="text-foreground/80 text-[clamp(0.9rem,0.8rem+0.5vw,1.125rem)] mb-6 sm:mb-8">
          Generate interior concepts with Stable Diffusion and explore different workflows.
        </p>

        <Button size="lg" onClick={handleStartCreating}>
          Start Creating
        </Button>
      </div>
    </section>
  );
}
