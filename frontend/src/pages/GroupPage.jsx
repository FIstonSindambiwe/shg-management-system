import { useEffect, useMemo, useState } from "react";
import { NavLink, useNavigate, useParams } from "react-router-dom";
import { api, errorText } from "../api";
import { useGroups } from "../groups.jsx";
import { L, both } from "../labels";

const today = () => new Date().toISOString().slice(0, 10);

/**
 * "KABEHO Christine, 0788123456"  -> surname KABEHO, first name Christine, phone
 * "Christine Kabeho"              -> first word is not all capitals, so the LAST word is the surname
 */
export function parseMemberLines(text) {
  return text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean).map((line) => {
    const [namePart, ...rest] = line.split(/[,;\t]/);
    const phone = (rest.join(" ").match(/\+?\d[\d\s]{6,}/)?.[0] || "").replace(/\s/g, "");
    const words = namePart.trim().split(/\s+/);
    let last, first;
    if (words.length === 1) { last = words[0]; first = words[0]; }
    else if (words[0] === words[0].toUpperCase() && /[A-Z]/.test(words[0])) { last = words[0]; first = words.slice(1).join(" "); }
    else { last = words[words.length - 1]; first = words.slice(0, -1).join(" "); }
    return { last_name: last, first_name: first, phone };
  });
}

function Meetings({ shg }) {
  const navigate = useNavigate();
  const [meetings, setMeetings] = useState([]);
  const [date, setDate] = useState(today());
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setMeetings([]);
    api.get(`/meetings/?shg=${shg.id}&ordering=-date`).then(({ data }) => setMeetings(data.results))
      .catch((e) => setError(errorText(e)));
  }, [shg.id]);

  async function create(e) {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      const { data } = await api.post("/meetings/", { shg: shg.id, date });
      navigate(`/meetings/${data.id}`);
    } catch (err) {
      const existing = meetings.find((m) => m.date === date);
      if (existing) navigate(`/meetings/${existing.id}`);
      else setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <form className="card row" onSubmit={create}>
        <label className="grow">
          <span>{both(L.newMeeting)}</span>
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </label>
        <button className="primary" disabled={busy}>{both(L.open)}</button>
      </form>
      {error && <p className="error">{error}</p>}
      <ul className="list">
        {meetings.map((m) => (
          <li key={m.id}>
            <button className="card tappable" onClick={() => navigate(`/meetings/${m.id}`)}>
              <strong>{m.date}</strong>
              <span className="muted">{m.submissions > 0 ? both(L.saved) : both(L.open)}</span>
            </button>
          </li>
        ))}
      </ul>
    </>
  );
}

function Members({ shg, onChanged }) {
  const [members, setMembers] = useState([]);
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [flash, setFlash] = useState("");
  const [busy, setBusy] = useState(false);
  const parsed = useMemo(() => parseMemberLines(text), [text]);

  const load = () => api.get(`/members/?shg=${shg.id}&page_size=500&ordering=member_code`)
    .then(({ data }) => setMembers(data.results));

  useEffect(() => { setMembers([]); load().catch((e) => setError(errorText(e))); }, [shg.id]); // eslint-disable-line

  async function save() {
    setBusy(true); setError(""); setFlash("");
    try {
      const { data } = await api.post("/members/bulk/", { shg: shg.id, members: parsed });
      setText("");
      setFlash(`${both(L.saved)}: ${data.length}`);
      await load();
      onChanged?.();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="card">
        <label>
          <span>{both(L.addMembers)} — {L.oneperline.rw}<br />{L.oneperline.en}</span>
          <textarea rows={6} value={text} onChange={(e) => setText(e.target.value)}
                    placeholder={"KABEHO Christine, 0788123456\nNYIRANDAGIJIMANA Laurence\nUWASE Odette"} />
        </label>
        {parsed.length > 0 && (
          <>
            <p className="muted small">{both(L.preview)} ({parsed.length})</p>
            <div className="table-wrap">
              <table className="grid-table compact">
                <thead><tr><th>#</th><th>{both(L.lastName)}</th><th>{both(L.firstName)}</th><th>{both(L.phone)}</th></tr></thead>
                <tbody>
                  {parsed.map((p, i) => (
                    <tr key={i}><td>{i + 1}</td><td>{p.last_name}</td><td>{p.first_name}</td><td>{p.phone}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
            <button className="primary big" disabled={busy} onClick={save}>
              {busy ? both(L.saving) : `${both(L.save)} (${parsed.length})`}
            </button>
          </>
        )}
        {flash && <p className="ok">{flash}</p>}
        {error && <p className="error">{error}</p>}
      </div>

      <div className="table-wrap">
        <table className="grid-table">
          <thead><tr><th>{both(L.code)}</th><th>{both(L.name)}</th><th>{both(L.phone)}</th></tr></thead>
          <tbody>
            {members.map((m) => (
              <tr key={m.id}><td className="muted">{m.member_code}</td><td>{m.full_name}</td><td>{m.phone}</td></tr>
            ))}
            {!members.length && <tr><td colSpan={3} className="muted">{both(L.noMembers)}</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}

export default function GroupPage({ tab }) {
  const { shgId } = useParams();
  const { groups, loaded, reload } = useGroups();
  const shg = groups.find((g) => String(g.id) === shgId);

  if (!loaded) return <main className="page"><p className="muted">{both(L.loading)}</p></main>;
  if (!shg) return <main className="page"><p className="error">Not found</p></main>;

  return (
    <main className="page">
      <h1 className="title">{shg.name}<small>{L.livelihood.en} · {shg.code}</small></h1>
      <nav className="tabs">
        <NavLink end to={`/groups/${shg.id}`} className={({ isActive }) => (isActive ? "on" : "")}>
          {both(L.meetings)}
        </NavLink>
        <NavLink to={`/groups/${shg.id}/members`} className={({ isActive }) => (isActive ? "on" : "")}>
          {both(L.members)} ({shg.member_count})
        </NavLink>
      </nav>
      {tab === "members" ? <Members shg={shg} onChanged={reload} /> : <Meetings shg={shg} />}
    </main>
  );
}
