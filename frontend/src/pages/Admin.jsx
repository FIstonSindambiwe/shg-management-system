import { useCallback, useEffect, useState } from "react";
import { api, errorText } from "../api";
import { useGroups } from "../groups.jsx";
import { L, both } from "../labels";
import ImportTab from "./ImportTab.jsx";

const STATUS = {
  ACTIVE: { rw: "Rirakora", en: "Active" }, INACTIVE: { rw: "Ntirikora", en: "Inactive" },
  SUSPENDED: { rw: "Ryahagaritswe", en: "Suspended" }, ARCHIVED: { rw: "Ryashyinguwe", en: "Archived" },
};
const ROLES = { LEADER: L.leader, VIEWER: { rw: "Ureba gusa", en: "Viewer" }, ADMIN: { rw: "Umuyobozi mukuru", en: "Admin" } };

function useFlash() {
  const [msg, setMsg] = useState(null);
  return {
    msg,
    ok: (t) => setMsg({ kind: "ok", t }),
    err: (e) => setMsg({ kind: "error", t: typeof e === "string" ? e : errorText(e) }),
    clear: () => setMsg(null),
  };
}

function Flash({ f }) {
  return f.msg ? <p className={f.msg.kind}>{f.msg.t}</p> : null;
}

/* --------------------------------------------------------------------- Groups */
function GroupsTab() {
  const { groups, reload } = useGroups();
  const [form, setForm] = useState({ name: "", location: "" });
  const [edit, setEdit] = useState(null);
  const f = useFlash();

  async function add(e) {
    e.preventDefault(); f.clear();
    try {
      await api.post("/shgs/", { name: form.name.trim(), location: form.location.trim() });
      setForm({ name: "", location: "" });
      await reload();
      f.ok(both(L.saved));
    } catch (err) { f.err(err); }
  }

  async function saveEdit() {
    f.clear();
    try {
      await api.patch(`/shgs/${edit.id}/`, { name: edit.name, location: edit.location, status: edit.status });
      setEdit(null);
      await reload();
      f.ok(both(L.saved));
    } catch (err) { f.err(err); }
  }

  return (
    <>
      <form className="card inline-form" onSubmit={add}>
        <label><span>{both(L.groupName)}</span>
          <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
        <label><span>{both(L.location)}</span>
          <input value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} /></label>
        <button className="primary" disabled={!form.name.trim()}>+ {both(L.newGroup)}</button>
      </form>
      <Flash f={f} />
      <div className="table-wrap">
        <table className="grid-table">
          <thead><tr>
            <th>{both(L.groupName)}</th><th>{both(L.code)}</th><th>{both(L.location)}</th>
            <th>{both(L.members)}</th><th>{both(L.leader)}</th><th>{both(L.status)}</th><th />
          </tr></thead>
          <tbody>
            {groups.map((g) => edit?.id === g.id ? (
              <tr key={g.id} className="editing">
                <td><input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></td>
                <td className="muted">{g.code}</td>
                <td><input value={edit.location} onChange={(e) => setEdit({ ...edit, location: e.target.value })} /></td>
                <td>{g.member_count}</td>
                <td>{g.current_leader?.name || "-"}</td>
                <td>
                  <select value={edit.status} onChange={(e) => setEdit({ ...edit, status: e.target.value })}>
                    {Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v.rw} ({v.en})</option>)}
                  </select>
                </td>
                <td className="actions">
                  <button className="primary small-btn" onClick={saveEdit}>{L.save.rw}</button>
                  <button className="link" onClick={() => setEdit(null)}>{L.cancel.rw}</button>
                </td>
              </tr>
            ) : (
              <tr key={g.id}>
                <td><strong>{g.name}</strong></td><td className="muted">{g.code}</td><td>{g.location || "-"}</td>
                <td>{g.member_count}</td>
                <td>{g.current_leader?.name || <span className="warn">-</span>}</td>
                <td>{STATUS[g.status]?.rw}</td>
                <td className="actions">
                  <button className="link" onClick={() => setEdit({ id: g.id, name: g.name, location: g.location || "", status: g.status })}>
                    {both(L.edit)}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

/* ---------------------------------------------------------------------- Users */
const EMPTY_USER = { first_name: "", last_name: "", username: "", phone: "", password: "", role: "LEADER", group: "" };

function UsersTab() {
  const { groups, reload: reloadGroups } = useGroups();
  const [users, setUsers] = useState([]);
  const [assignments, setAssignments] = useState([]);
  const [form, setForm] = useState(EMPTY_USER);
  const [busy, setBusy] = useState(false);
  const f = useFlash();

  const load = useCallback(async () => {
    const [u, a] = await Promise.all([
      api.get("/users/?page_size=500"),
      api.get("/leader-assignments/?active=true&page_size=500"),
    ]);
    setUsers(u.data.results);
    setAssignments(a.data.results);
  }, []);

  useEffect(() => { load().catch(f.err); }, [load]); // eslint-disable-line

  /** Ends the group's current leader (if any), then assigns this user. */
  async function assign(userId, groupId) {
    const current = assignments.find((a) => String(a.shg) === String(groupId));
    if (current && current.leader === userId) return;
    if (current) await api.post(`/leader-assignments/${current.id}/end/`);
    await api.post("/leader-assignments/", { shg: Number(groupId), leader: userId });
  }

  async function create(e) {
    e.preventDefault(); f.clear(); setBusy(true);
    try {
      const { group, ...body } = form;
      const { data: user } = await api.post("/users/", body);
      if (group && form.role === "LEADER") await assign(user.id, group);
      setForm(EMPTY_USER);
      await Promise.all([load(), reloadGroups()]);
      f.ok(`${both(L.saved)}: ${user.username}`);
    } catch (err) { f.err(err); } finally { setBusy(false); }
  }

  async function changeGroup(u, groupId) {
    f.clear();
    try {
      if (groupId) await assign(u.id, groupId);
      await Promise.all([load(), reloadGroups()]);
      f.ok(both(L.saved));
    } catch (err) { f.err(err); }
  }

  async function resetPassword(u) {
    const pw = window.prompt(`${both(L.resetPassword)}: ${u.username}\n(min. 8)`);
    if (!pw) return;
    f.clear();
    try { await api.patch(`/users/${u.id}/`, { password: pw }); f.ok(both(L.saved)); } catch (err) { f.err(err); }
  }

  async function toggleActive(u) {
    f.clear();
    try { await api.patch(`/users/${u.id}/`, { is_active: !u.is_active }); await load(); } catch (err) { f.err(err); }
  }

  const ledBy = (userId) => assignments.filter((a) => a.leader === userId);

  return (
    <>
      <form className="card user-form" onSubmit={create}>
        <h2>{L.newLeader.rw} <small>{L.newLeader.en}</small></h2>
        <div className="form-grid">
          <label><span>{both(L.firstName)}</span>
            <input value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} /></label>
          <label><span>{both(L.lastName)}</span>
            <input value={form.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} /></label>
          <label><span>{both(L.username)}</span>
            <input value={form.username} autoCapitalize="none"
                   onChange={(e) => setForm({ ...form, username: e.target.value.trim().toLowerCase() })} /></label>
          <label><span>{both(L.phone)}</span>
            <input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></label>
          <label><span>{both(L.password)}</span>
            <input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></label>
          <label><span>{both(L.role)}</span>
            <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
              {Object.entries(ROLES).map(([k, v]) => <option key={k} value={k}>{v.rw} ({v.en})</option>)}
            </select></label>
          {form.role === "LEADER" && (
            <label><span>{both(L.group)}</span>
              <select value={form.group} onChange={(e) => setForm({ ...form, group: e.target.value })}>
                <option value="">-</option>
                {groups.map((g) => <option key={g.id} value={g.id}>{g.name}{g.current_leader ? ` (${g.current_leader.name})` : ""}</option>)}
              </select></label>
          )}
        </div>
        <button className="primary" disabled={busy || !form.username || form.password.length < 8}>
          {busy ? both(L.saving) : `+ ${both(L.add)}`}
        </button>
        <p className="muted small">
          Iyo itsinda rifite umuyobozi, uwo mushya aramusimbura. (If the group already has a leader, the new one replaces them.)
        </p>
      </form>
      <Flash f={f} />
      <div className="table-wrap">
        <table className="grid-table">
          <thead><tr>
            <th>{both(L.username)}</th><th>{both(L.name)}</th><th>{both(L.role)}</th>
            <th>{both(L.group)}</th><th>{both(L.status)}</th><th />
          </tr></thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} className={u.is_active ? "" : "inactive-row"}>
                <td><strong>{u.username}</strong></td>
                <td>{[u.first_name, u.last_name].filter(Boolean).join(" ") || "-"}<small>{u.phone}</small></td>
                <td>{ROLES[u.role]?.rw}<small>{ROLES[u.role]?.en}</small></td>
                <td>
                  {u.role === "LEADER" ? (
                    <select value={ledBy(u.id)[0]?.shg ?? ""} onChange={(e) => changeGroup(u, e.target.value)}>
                      <option value="">-</option>
                      {groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
                    </select>
                  ) : <span className="muted">{L.allGroups.rw}</span>}
                </td>
                <td>{u.is_active ? L.active.rw : L.inactive.rw}</td>
                <td className="actions">
                  <button className="link" onClick={() => resetPassword(u)}>{L.resetPassword.rw}</button>
                  <button className="link" onClick={() => toggleActive(u)}>
                    {u.is_active ? "Hagarika (Deactivate)" : "Subiza (Activate)"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

/* ------------------------------------------------------------------- Settings */
function SettingsTab() {
  const { groups, reload } = useGroups();
  const [shgId, setShgId] = useState("");
  const [cycle, setCycle] = useState(null);
  const [rules, setRules] = useState("");
  const f = useFlash();

  useEffect(() => {
    if (!shgId && groups.length) setShgId(String(groups[0].id));
  }, [groups, shgId]);

  useEffect(() => {
    if (!shgId) return;
    setCycle(null); f.clear();
    const g = groups.find((x) => String(x.id) === shgId);
    setRules(g?.rules_note || "");
    api.get(`/cycles/?shg=${shgId}&status=OPEN`).then(({ data }) => setCycle(data.results[0] || null)).catch(f.err);
  }, [shgId]); // eslint-disable-line

  const set = (k, v) => setCycle({ ...cycle, [k]: v });

  async function save(e) {
    e.preventDefault(); f.clear();
    try {
      const fields = ["ingoboka_weekly", "mutuelle_weekly", "loan_term_months", "loan_multiplier", "fines_in_profit",
                      "share_price", "interest_rate_percent"];
      const body = Object.fromEntries(fields.map((k) => [k, cycle[k]]));
      const { data } = await api.patch(`/cycles/${cycle.id}/`, body);
      setCycle(data);
      await api.patch(`/shgs/${shgId}/`, { rules_note: rules });
      await reload();
      f.ok(both(L.saved));
    } catch (err) { f.err(err); }
  }

  const field = (key, label, props = {}) => (
    <label><span>{label}</span>
      <input value={cycle[key] ?? ""} onChange={(e) => set(key, e.target.value)} inputMode="decimal" {...props} /></label>
  );

  return (
    <>
      <div className="card">
        <label><span>{both(L.group)}</span>
          <select value={shgId} onChange={(e) => setShgId(e.target.value)}>
            {groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
          </select></label>
      </div>
      <Flash f={f} />
      {cycle && (
        <form className="card" onSubmit={save}>
          <h2>{L.settings.rw} {cycle.name} <small>{L.settings.en} - savings cycle {cycle.start_date} to {cycle.end_date}</small></h2>
          <div className="form-grid">
            {field("share_price", "Igiciro cy'umugabane (Share price, RWF)")}
            {field("ingoboka_weekly", "Ingoboka buri cyumweru (Social fund per week)")}
            {field("mutuelle_weekly", "Mituweli buri cyumweru (Mutuelle per week)")}
            {field("interest_rate_percent", "Inyungu % (Interest %)")}
            {field("loan_term_months", "Amezi yo kwishyura (Months to repay)")}
            {field("loan_multiplier", "Inguzanyo ntarengwa x imigabane (Loan limit x shares)")}
            <label className="check"><input type="checkbox" checked={!!cycle.fines_in_profit}
                   onChange={(e) => set("fines_in_profit", e.target.checked)} />
              <span>Ibihano bijya mu nyungu zigabanywa (Fines count in the year-end share-out)</span></label>
          </div>
          <label><span>Amategeko y'itsinda (Group rules, e.g. late-loan fine)</span>
            <textarea rows={3} value={rules} onChange={(e) => setRules(e.target.value)} /></label>
          <p className="muted small">
            Igiciro cy'umugabane n'inyungu ntibihindurwa iyo amafaranga yatangiye kwandikwa.
            (Share price and interest can't change once money is recorded in the cycle.)
          </p>
          <button className="primary">{both(L.save)}</button>
        </form>
      )}
    </>
  );
}

export default function Admin() {
  const [tab, setTab] = useState("groups");
  const tabs = [["groups", L.groups], ["users", L.users], ["settings", L.settings], ["import", { rw: "Kwinjiza Excel", en: "Import Excel" }]];
  return (
    <main className="page wide">
      <h1 className="title">{L.manage.rw}<small>{L.manage.en} - admin</small></h1>
      <nav className="tabs">
        {tabs.map(([k, label]) => (
          <a key={k} href={`#${k}`} className={tab === k ? "on" : ""} onClick={(e) => { e.preventDefault(); setTab(k); }}>
            {both(label)}
          </a>
        ))}
      </nav>
      {tab === "groups" && <GroupsTab />}
      {tab === "users" && <UsersTab />}
      {tab === "settings" && <SettingsTab />}
      {tab === "import" && <ImportTab />}
    </main>
  );
}