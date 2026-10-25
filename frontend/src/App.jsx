import { Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { LiveProvider } from "./context/LiveContext";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import Chat from "./pages/Chat";
import Decisions from "./pages/Decisions";
import Memories from "./pages/Memories";
import Graph from "./pages/Graph";
import Timeline from "./pages/Timeline";
import Live from "./pages/Live";
import Import from "./pages/Import";
import Analytics from "./pages/Analytics";
import Settings from "./pages/Settings";

function Guarded() {
  const { token, ready, wsId } = useAuth();
  if (!ready) return <div className="p-10 text-dim">Loading…</div>;
  if (!token) return <Navigate to="/login" replace />;
  if (!wsId) return <div className="p-10 text-dim">Loading workspace…</div>;
  return <LiveProvider><Layout /></LiveProvider>;
}

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route element={<Guarded />}>
          <Route path="/" element={<Chat />} />
          <Route path="/decisions" element={<Decisions />} />
          <Route path="/memories" element={<Memories />} />
          <Route path="/graph" element={<Graph />} />
          <Route path="/timeline" element={<Timeline />} />
          <Route path="/live" element={<Live />} />
          <Route path="/import" element={<Import />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/settings" element={<Settings />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  );
}
