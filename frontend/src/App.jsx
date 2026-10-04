import axios from "axios";
import { lazy, Suspense } from "react";

import { store } from "./store";
import { Provider } from "react-redux";
import { Toaster } from "react-hot-toast";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";

import Navbar from "./components/NavBar";
import Footer from "./components/Footer";
import PrivateRoute from "./components/PrivateRoute";
import AuthModal from "./components/AuthModal";
import { AuthModalProvider, authModalController } from "./context/AuthModalContext";
import { logout } from "./features/auth/authSlice";
// import { ColorModeProvider } from "./components/ui/color-mode"

import LandingPage from "./views/landing/LandingPage";
import Workflows from "./views/workflows/Workflows";
import TextToImage from "./views/workflows/text-to-image/TextToImage";
import ImageToImage from "./views/workflows/image-to-image/ImageToImage";
import Inpainting from "./views/workflows/inpainting/Inpainting";
import Outpainting from "./views/workflows/Outpainting/Outpainting";
import ControlNet from "./views/workflows/control-net/ControlNet";
import Canvas from "./views/workflows/canvas/Canvas";
import FurnitureReplace from "./views/workflows/furniture-replace/FurnitureReplace";
// import BoundingBoxes from "./views/workflows/bounding-boxes/BoundingBoxes";
import Prompts from "./views/prompts/Prompts";
import Gallery from "./views/gallery/Gallery";
import Logout from "./views/account/logout/Logout";
import Profile from "./views/account/profile/Profile";
import Health from "./views/health/Health";
import AdminPanel from "./views/adminPanel/AdminPanel";
import AdminRoute from "./components/AdminRoute";
import UserDetails from "./views/adminPanel/UserDetails";
import Error from "./views/error/Error";

const Panorama360 = lazy(() => import("./views/workflows/panorama-360/Panorama360"));

axios.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 && !authModalController.isOpen) {
      store.dispatch(logout());
      authModalController.openLogin();
    }
    return Promise.reject(error);
  }
);

const App = () => (
  <Provider store={store}>
    {/* <ColorModeProvider /> */}
    <BrowserRouter>
      <AuthModalProvider>
        <div className="min-h-screen flex flex-col">
          <Navbar />
          <Toaster position="top-right" containerStyle={{ top: 88 }} />
          <AuthModal />
          <main className="flex-1 flex flex-col">
            <Routes>
              <Route path="/" element={<Navigate to="/views/landing" replace />} />
              <Route path="/views/account/login" element={<Navigate to="/views/landing" replace state={{ authModal: "login" }} />} />
              <Route path="/views/account/register" element={<Navigate to="/views/landing" replace state={{ authModal: "register" }} />} />
              <Route path="/views/landing" element={<LandingPage />} />
              <Route path="/views/workflows/text-to-image" element={<PrivateRoute><TextToImage /></PrivateRoute>} />
              <Route path="/views/workflows/panorama-360" element={<PrivateRoute><Suspense fallback={<div role="status" className="grid min-h-[50vh] place-items-center text-muted">Loading workflow...</div>}><Panorama360 /></Suspense></PrivateRoute>} />
              <Route path="/views/workflows/image-to-image" element={<PrivateRoute><ImageToImage /></PrivateRoute>} />
              <Route path="/views/workflows/inpainting" element={<PrivateRoute><Inpainting /></PrivateRoute>} />
              <Route path="/views/workflows/outpainting" element={<PrivateRoute><Outpainting /></PrivateRoute>} />
              <Route path="/views/workflows/control-net" element={<PrivateRoute><ControlNet /></PrivateRoute>} />
              <Route path="/views/workflows/canvas" element={<PrivateRoute><Canvas /></PrivateRoute>} />
              <Route path="/views/workflows/furniture-replace" element={<PrivateRoute><FurnitureReplace /></PrivateRoute>} />
              {/* <Route path="/views/workflows/bounding-boxes" element={<PrivateRoute><BoundingBoxes /></PrivateRoute>} /> */}
              <Route path="/views/prompts" element={<PrivateRoute><Prompts /></PrivateRoute>} />
              <Route path="/views/gallery" element={<PrivateRoute><Gallery /></PrivateRoute>} />
              <Route path="/views/account/logout" element={<PrivateRoute><Logout /></PrivateRoute>} />
              <Route path="/views/account/profile" element={<PrivateRoute><Profile /></PrivateRoute>} />
              <Route path="/views/workflows" element={<PrivateRoute><Workflows /></PrivateRoute>} />
              <Route path="/views/health" element={<Health />} />
              <Route path="/views/adminPanel" element={<AdminRoute><AdminPanel /></AdminRoute>} />
              <Route path="/views/adminPanel/user/:id" element={<AdminRoute><UserDetails /></AdminRoute>} />
              <Route path="*" element={<Error/>} />
            </Routes>
          </main>
          <Footer />
        </div>
      </AuthModalProvider>
    </BrowserRouter>
  </Provider>
);

export default App;
