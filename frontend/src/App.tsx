import {
  BrowserRouter as Router,
  Routes,
  Route,
  Navigate,
} from "react-router-dom";
import { Toaster, ToastBar, toast } from "react-hot-toast";
import { X } from "lucide-react";
import { AuthProvider } from "./contexts/AuthContext";
import { WatchlistProvider } from "./contexts/WatchlistContext";
import { NotificationProvider } from "./contexts/NotificationContext";
import { IndicatorThresholdsProvider } from "./contexts/IndicatorThresholdsContext";
import ProtectedRoute from "./components/ProtectedRoute";
import AdminRoute from "./components/AdminRoute";
import Layout from "./components/layout/Layout";
import Login from "./pages/Login";
import Register from "./pages/Register";
import ForgotPassword from "./pages/ForgotPassword";
import Dashboard from "./pages/Dashboard";
import Profile from "./pages/Profile";
import Settings from "./pages/Settings";
import ContactSupport from "./pages/ContactSupport";
import Stocks from "./pages/Stocks";
import StockDetail from "./pages/StockDetail";
import IndicatorDetail from "./pages/IndicatorDetail";
import Indicators from "./pages/Indicators";
import PatternDetail from "./pages/PatternDetail";
import Patterns from "./pages/Patterns";
import PortfolioPage from "./pages/Portfolio";
import MassiveLive from "./pages/MassiveLive";
import TradingBots from "./pages/TradingBots";
import TradingBotDetail from "./pages/TradingBotDetail";
import EditBot from "./pages/EditBot";
import BotSignalHistoryPage from "./pages/BotSignalHistory";
import BotExecutionDetail from "./pages/BotExecutionDetail";
import BotSystemDocumentation from "./pages/admin/BotSystemDocumentation";
import BotSimulationList from "./pages/simulations/BotSimulationList";
import BotSimulationCreate from "./pages/simulations/BotSimulationCreate";
import BotSimulationDetail from "./pages/simulations/BotSimulationDetail";
import BotSimulationEdit from "./pages/simulations/BotSimulationEdit";
import BotSimulationResults from "./pages/simulations/BotSimulationResults";
import BotSimulationProgress from "./pages/simulations/BotSimulationProgress";
import BotSimulationResultDetail from "./pages/simulations/BotSimulationResultDetail";

function App() {
  return (
    <AuthProvider>
      <NotificationProvider>
        <IndicatorThresholdsProvider>
          <Router>
            <div className="App">
              <Routes>
                {/* Public routes */}
                <Route path="/login" element={<Login />} />
                <Route path="/register" element={<Register />} />
                <Route path="/forgot-password" element={<ForgotPassword />} />

                {/* Protected routes */}
                <Route
                  path="/"
                  element={
                    <ProtectedRoute>
                      <WatchlistProvider>
                        <Layout />
                      </WatchlistProvider>
                    </ProtectedRoute>
                  }
                >
                  <Route index element={<Navigate to="/dashboard" replace />} />
                  <Route path="dashboard" element={<Dashboard />} />
                  <Route path="profile" element={<Profile />} />
                  <Route path="settings" element={<Settings />} />
                  <Route path="contact-support" element={<ContactSupport />} />

                  {/* Stock routes */}
                  <Route path="stocks" element={<Stocks />} />
                  <Route path="stocks/:symbol" element={<StockDetail />} />

                  {/* Indicator routes */}
                  <Route path="indicators" element={<Indicators />} />
                  <Route path="indicators/:id" element={<IndicatorDetail />} />

                  {/* Pattern routes */}
                  <Route path="patterns" element={<Patterns />} />
                  <Route path="patterns/:id" element={<PatternDetail />} />

                  {/* Portfolio route */}
                  <Route path="portfolio" element={<PortfolioPage />} />

                  {/* Massive live streaming dashboard */}
                  <Route path="massive-live" element={<MassiveLive />} />

                  {/* Trading Bots routes - Admin only */}
                  <Route
                    path="trading-bots"
                    element={
                      <AdminRoute>
                        <TradingBots />
                      </AdminRoute>
                    }
                  />
                  <Route
                    path="trading-bots/:id"
                    element={
                      <AdminRoute>
                        <TradingBotDetail />
                      </AdminRoute>
                    }
                  />
                  <Route
                    path="trading-bots/:id/edit"
                    element={
                      <AdminRoute>
                        <EditBot />
                      </AdminRoute>
                    }
                  />
                  <Route
                    path="trading-bots/:botId/signals"
                    element={
                      <AdminRoute>
                        <BotSignalHistoryPage />
                      </AdminRoute>
                    }
                  />
                  <Route
                    path="executions/:id"
                    element={
                      <AdminRoute>
                        <BotExecutionDetail />
                      </AdminRoute>
                    }
                  />
                  <Route
                    path="trading-bots/documentation"
                    element={
                      <AdminRoute>
                        <BotSystemDocumentation />
                      </AdminRoute>
                    }
                  />

                  {/* Simulation routes - Admin only */}
                  <Route
                    path="simulations"
                    element={
                      <AdminRoute>
                        <BotSimulationList />
                      </AdminRoute>
                    }
                  />
                  <Route
                    path="simulations/create"
                    element={
                      <AdminRoute>
                        <BotSimulationCreate />
                      </AdminRoute>
                    }
                  />
                  <Route
                    path="simulations/:id"
                    element={
                      <AdminRoute>
                        <BotSimulationDetail />
                      </AdminRoute>
                    }
                  />
                  <Route
                    path="simulations/:id/edit"
                    element={
                      <AdminRoute>
                        <BotSimulationEdit />
                      </AdminRoute>
                    }
                  />
                  <Route
                    path="simulations/:id/results/:configId"
                    element={
                      <AdminRoute>
                        <BotSimulationResultDetail />
                      </AdminRoute>
                    }
                  />
                  <Route
                    path="simulations/:id/progress"
                    element={
                      <AdminRoute>
                        <BotSimulationProgress />
                      </AdminRoute>
                    }
                  />
                  <Route
                    path="simulations/:id/results"
                    element={
                      <AdminRoute>
                        <BotSimulationResults />
                      </AdminRoute>
                    }
                  />

                  {/* Catch all route for protected routes */}
                  <Route
                    path="*"
                    element={<Navigate to="/dashboard" replace />}
                  />
                </Route>
              </Routes>

              {/* Toast notifications */}
              <Toaster
                position="top-right"
                toastOptions={{
                  duration: 4000,
                  style: {
                    background: "rgba(255, 255, 255, 0.1)",
                    backdropFilter: "blur(10px)",
                    color: "#fff",
                    border: "1px solid rgba(255, 255, 255, 0.2)",
                  },
                  success: {
                    iconTheme: {
                      primary: "#10b981",
                      secondary: "#fff",
                    },
                  },
                  error: {
                    iconTheme: {
                      primary: "#ef4444",
                      secondary: "#fff",
                    },
                  },
                }}
              >
                {(t) => (
                  <ToastBar toast={t}>
                    {({ icon, message }) => (
                      <div className="toast-container flex items-center gap-2 w-full group">
                        {icon}
                        <div className="flex-1">{message}</div>
                        <button
                          onClick={() => toast.dismiss(t.id)}
                          className="toast-close-button opacity-0 group-hover:opacity-100 transition-opacity duration-200 p-1 hover:bg-white/20 rounded flex items-center justify-center min-w-[20px] min-h-[20px] text-white/80 hover:text-white"
                          aria-label="Close"
                        >
                          <X className="w-4 h-4" />
                        </button>
                      </div>
                    )}
                  </ToastBar>
                )}
              </Toaster>
            </div>
          </Router>
        </IndicatorThresholdsProvider>
      </NotificationProvider>
    </AuthProvider>
  );
}

export default App;
