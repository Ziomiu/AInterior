import { useEffect, useState } from "react";
import axios from "axios";
import { useDispatch } from "react-redux";

import { useAuthModal } from "../context/AuthModalContext";
import { toaster } from "./ui/toaster";
import Button from "./ui/Button";
import Input from "./ui/Input";
import { loginSuccess } from "../features/auth/authSlice";

const isValidEmail = (email) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);

const initialForm = { first_name: "", last_name: "", email: "", password: "" };

export default function AuthModal() {
  const { mode, isOpen, close, openLogin, openRegister } = useAuthModal();
  const dispatch = useDispatch();

  const [form, setForm] = useState(initialForm);
  const [loading, setLoading] = useState(false);
  const [renderedMode, setRenderedMode] = useState(mode);

  if (mode !== renderedMode) {
    setRenderedMode(mode);
    setForm(initialForm);
  }

  const isLogin = renderedMode === "login";

  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e) => {
      if (e.key === "Escape") close();
    };

    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.body.style.overflow = "";
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen, close]);

  if (!isOpen) return null;

  const handleChange = (e) => {
    setForm({ ...form, [e.target.name]: e.target.value });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();

    const { first_name, last_name, email, password } = form;

    if (!email || !password || (!isLogin && (!first_name || !last_name))) {
      toaster.create({
        title: "Missing fields",
        description: "Please fill in all the fields.",
        status: "warning",
      });
      return;
    }

    if (!isValidEmail(email)) {
      toaster.create({
        title: "Invalid email",
        description: "Please enter a valid email address.",
        status: "error",
      });
      return;
    }

    setLoading(true);

    try {
      if (isLogin) {
        const res = await axios.post("/api/auth/login", { email, password });
        const { access_token, first_name, last_name, email: userEmail, role } = res.data;

        localStorage.setItem("token", access_token);
        dispatch(
          loginSuccess({
            user: { first_name, last_name, email: userEmail, role },
            token: access_token,
          })
        );

        toaster.create({ title: "Logged in successfully", status: "success" });
      } else {
        await axios.post("/api/auth/register", { first_name, last_name, email, password, role: "user" });
        const loginRes = await axios.post("/api/auth/login", { email, password });
        const { access_token, first_name: registeredFirstName, last_name: registeredLastName, email: registeredEmail, role } = loginRes.data;

        localStorage.setItem("token", access_token);
        dispatch(
          loginSuccess({
            user: { first_name: registeredFirstName, last_name: registeredLastName, email: registeredEmail, role },
            token: access_token,
          })
        );

        toaster.create({ title: "Account created!", status: "success" });
      }

      close();
    } catch (error) {
      console.error(`${isLogin ? "Login" : "Registration"} error:`, error);

      const fallback = isLogin
        ? "Login failed. Please check your credentials and try again."
        : "Something went wrong. Try again.";

      const message =
        error?.response?.data?.detail === "Email already registered"
          ? "An account with this email already exists."
          : error?.response?.data?.detail || fallback;

      toaster.create({
        title: isLogin ? "Login failed" : "Registration failed",
        description: message,
        status: "error",
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/40 backdrop-blur-sm px-4"
      onClick={close}
    >
      <div
        className="relative w-full max-w-md rounded-2xl bg-[#fbf9f4] shadow-2xl p-8 sm:p-10"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          onClick={close}
          aria-label="Close"
          className="absolute top-5 right-5 text-muted/60 hover:text-foreground transition-colors cursor-pointer text-xl leading-none"
        >
          ×
        </button>

        <h2 className="font-serif text-3xl text-foreground mb-6">{isLogin ? "Login" : "Sign Up"}</h2>

        <form onSubmit={handleSubmit} className="flex flex-col gap-5">
          {!isLogin && (
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label htmlFor="first_name" className="block text-sm text-foreground mb-1.5">
                  First Name
                </label>
                <Input
                  id="first_name"
                  name="first_name"
                  value={form.first_name}
                  onChange={handleChange}
                />
              </div>
              <div>
                <label htmlFor="last_name" className="block text-sm text-foreground mb-1.5">
                  Last Name
                </label>
                <Input
                  id="last_name"
                  name="last_name"
                  value={form.last_name}
                  onChange={handleChange}
                />
              </div>
            </div>
          )}

          <div>
            <label htmlFor="email" className="block text-sm text-foreground mb-1.5">
              Email
            </label>
            <Input
              id="email"
              name="email"
              type="email"
              value={form.email}
              onChange={handleChange}
            />
          </div>

          <div>
            <label htmlFor="password" className="block text-sm text-foreground mb-1.5">
              Password
            </label>
            <Input
              id="password"
              name="password"
              type="password"
              value={form.password}
              onChange={handleChange}
            />
          </div>

          <Button
            type="submit"
            variant="accent"
            disabled={loading}
            className="mt-2 w-full normal-case tracking-normal text-sm py-3"
          >
            {loading ? (isLogin ? "Logging in..." : "Signing up...") : isLogin ? "Login" : "Sign Up"}
          </Button>
        </form>

        <p className="text-sm text-center text-muted mt-6">
          {isLogin ? (
            <>
              Don't have an account?{" "}
              <button type="button" onClick={openRegister} className="text-accent font-semibold cursor-pointer hover:underline">
                Sign up
              </button>
            </>
          ) : (
            <>
              Already have an account?{" "}
              <button type="button" onClick={openLogin} className="text-accent font-semibold cursor-pointer hover:underline">
                Login
              </button>
            </>
          )}
        </p>
      </div>
    </div>
  );
}
