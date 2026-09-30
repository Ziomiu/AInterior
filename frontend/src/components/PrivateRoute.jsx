import { useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { Navigate } from 'react-router-dom';
import { logout } from '../features/auth/authSlice';

const isTokenValid = (token) => {
  if (!token) return false;
  try {
    const payload = JSON.parse(atob(token.split('.')[1]));
    return payload.exp * 1000 > Date.now();
  } catch {
    return false;
  }
};

const PrivateRoute = ({ children }) => {
  const dispatch = useDispatch();
  const isAuthenticated = useSelector(state => state.auth.isAuthenticated);
  const token = localStorage.getItem("token");
  const isValid = isAuthenticated && isTokenValid(token);

  useEffect(() => {
    if (!isValid && isAuthenticated) dispatch(logout());
  }, [isValid, isAuthenticated, dispatch]);

  if (!isValid) return <Navigate to="/views/account/login" replace />;

  return children;
};

export default PrivateRoute;
