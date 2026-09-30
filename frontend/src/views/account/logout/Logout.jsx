import { useEffect } from "react";
import { useDispatch } from "react-redux";
import { useNavigate } from "react-router-dom";
import { logout } from "../../../features/auth/authSlice";

export default function Logout() {
  const dispatch = useDispatch();
  const navigate = useNavigate();

  useEffect(() => {
    dispatch(logout());
    navigate("/views/landing");
  }, [dispatch, navigate]);

  return (
    <div className="min-h-screen flex flex-col items-center justify-center">
      <h1 className="text-4xl text-muted mb-4">Logging out...</h1>
      <div className="animate-spin rounded-full h-12 w-12 border-t-4 border-accent border-solid"></div>
    </div>
  );
}
