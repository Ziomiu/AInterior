import { createContext, useContext, useCallback, useEffect, useMemo, useState } from "react";

const AuthModalContext = createContext(null);

// Lets code outside the React tree (the axios 401 interceptor) trigger the modal.
export const authModalController = { openLogin: () => {}, openRegister: () => {} };

export function AuthModalProvider({ children }) {
  const [mode, setMode] = useState(null);

  const openLogin = useCallback(() => setMode("login"), []);
  const openRegister = useCallback(() => setMode("register"), []);
  const close = useCallback(() => setMode(null), []);

  useEffect(() => {
    authModalController.openLogin = openLogin;
    authModalController.openRegister = openRegister;
  }, [openLogin, openRegister]);

  const value = useMemo(
    () => ({ mode, isOpen: mode !== null, openLogin, openRegister, close }),
    [mode, openLogin, openRegister, close]
  );

  return <AuthModalContext.Provider value={value}>{children}</AuthModalContext.Provider>;
}

export function useAuthModal() {
  const context = useContext(AuthModalContext);
  if (!context) throw new Error("useAuthModal must be used within an AuthModalProvider");
  return context;
}
