import { useState } from "react";
import { Navigate, NavLink, Outlet, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { api, errorText } from "./api";
import { useAuth } from "./auth.jsx";
import { GroupsProvider, useGroups } from "./groups.jsx";
import { L, both } from "./labels";
import Admin from "./pages/Admin.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import GroupPage from "./pages/GroupPage.jsx";
import Login from "./pages/Login.jsx";
import Reports from "./pages/Reports.jsx";
import WeeklySheet from "./pages/WeeklySheet.jsx";

function Sidebar({ open, onClose }) {
  const { user } = useAuth();
  const { groups, reload } = useGroups();
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [adding, setAdding] = useState(false);
  const navigate = useNavigate();
  const isAdmin = user?.role === "ADMIN";

  async function addGroup(e) {
    e.preventDefault();
    setError("");
    try {
      const { data } = await api.post("/shgs/", { name: name.trim() });
      setName(""); setAdding(false);
      await reload();
      navigate(`/groups/${data.id}/members`);
      onClose();
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <>
      <div className={`scrim ${open ? "show" : ""}`} onClick={onClose} />
      <aside className={`sidebar ${open ? "open" : ""}`}>
        <p className="side-section">{L.livelihood.en}<small>{L.livelihood.rw}</small></p>
        <nav>
          {groups.map((g) => (
            <NavLink key={g.id} to={`/groups/${g.id}`} onClick={onClose}
                     className={({ isActive }) => `side-link ${isActive ? "active" : ""}`}>
              <span>{g.name}</span>
              <small>{g.member_count}</small>
            </NavLink>
          ))}
          {!groups.length && <p className="muted small pad">-</p>}
        </nav>
        {isAdmin && (adding ? (
          <form className="side-add" onSubmit={addGroup}>
            <input autoFocus placeholder={both(L.groupName)} value={name} onChange={(e) => setName(e.target.value)} />
            <div className="row-btns">
              <button className="primary" disabled={!name.trim()}>{both(L.add)}</button>
              <button type="button" className="link light" onClick={() => { setAdding(false); setError(""); }}>
                {both(L.cancel)}
              </button>
            </div>
            {error && <p className="error light">{error}</p>}
          </form>
        ) : (
          <button className="side-new" onClick={() => setAdding(true)}>+ {both(L.newGroup)}</button>
        ))}

        <hr className="side-divider" />
        <NavLink to="/dashboard" onClick={onClose} className={({ isActive }) => `side-link top ${isActive ? "active" : ""}`}>
          <span>{L.dashboard.rw}</span><small>{L.dashboard.en}</small>
        </NavLink>
        <NavLink to="/reports" onClick={onClose} className={({ isActive }) => `side-link top ${isActive ? "active" : ""}`}>
          <span>{L.report.rw}</span><small>{L.report.en}</small>
        </NavLink>
        {isAdmin && (
          <NavLink to="/admin" onClick={onClose} className={({ isActive }) => `side-link top ${isActive ? "active" : ""}`}>
            <span>{L.manage.rw}</span><small>{L.manage.en}</small>
          </NavLink>
        )}
      </aside>
    </>
  );
}

function Shell({ children }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  return (
    <div className="shell">
      <header className="topbar">
        <button className="burger" aria-label={L.menu.en} onClick={() => setOpen(true)}>&#9776;</button>
        <button className="brand" onClick={() => navigate("/")}>{L.appName.rw}</button>
        <div className="topbar-right">
          <span className="who">{user.full_name || user.username}</span>
          <button className="logout" onClick={() => { logout(); navigate("/login"); }}>{both(L.logout)}</button>
        </div>
      </header>
      <Sidebar open={open} onClose={() => setOpen(false)} />
      <div className="content">{children}</div>
    </div>
  );
}

function Home() {
  return <Navigate to="/dashboard" replace />;
}

function AdminOnly({ children }) {
  const { user } = useAuth();
  return user?.role === "ADMIN" ? children : <Navigate to="/dashboard" replace />;
}

function ProtectedLayout() {
  const { user } = useAuth();
  const location = useLocation();
  if (!user) return <Navigate to="/login" replace state={{ from: location }} />;
  return <GroupsProvider><Shell><Outlet /></Shell></GroupsProvider>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<ProtectedLayout />}>
        <Route path="/" element={<Home />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/reports" element={<Reports />} />
        <Route path="/admin" element={<AdminOnly><Admin /></AdminOnly>} />
        <Route path="/groups/:shgId" element={<GroupPage tab="meetings" />} />
        <Route path="/groups/:shgId/members" element={<GroupPage tab="members" />} />
        <Route path="/meetings/:id" element={<WeeklySheet />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}