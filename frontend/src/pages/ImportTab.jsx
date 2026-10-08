import { useState } from "react";
import { api, errorText } from "../api";
import { useGroups } from "../groups.jsx";
import { both, L } from "../labels";

async function saveBlob(res, fallback) {
  const name = /filename="([^"]+)"/.exec(res.headers["content-disposition"] || "")?.[1] || fallback;
  const url = URL.createObjectURL(res.data);
  const a = document.createElement("a");
  a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

/** Admin: bring a whole Excel file (members + dated entries) into one group. Check first, then import. */
export default function ImportTab() {
  const { groups, reload } = useGroups();
  const [shg, setShg] = useState("");
  const [file, setFile] = useState(null);
  const [result, setResult] = useState(null);
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function template() {
    try { await saveBlob(await api.get("/imports/template/", { responseType: "blob" }), "shg-import-template.xlsx"); }
    catch (e) { setError(errorText(e)); }
  }

  async function send(dryRun) {
    setBusy(true); setError(""); setResult(null);
    const fd = new FormData();
    fd.append("file", file); fd.append("shg", shg); fd.append("dry_run", dryRun ? "true" : "false");
    try {
      const { data } = await api.post("/imports/xlsx/", fd, { headers: { "Content-Type": "multipart/form-data" } });
      setResult(data);
      setChecked(dryRun);
      if (!dryRun) { setFile(null); await reload(); }
    } catch (e) {
      if (e.response?.data?.errors) { setResult(e.response.data); setChecked(false); }
      else setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  const reset = () => { setResult(null); setChecked(false); };

  return (
    <>
      <div className="card">
        <h2>Kwinjiza Excel <small>Import from Excel</small></h2>
        <ol className="steps-list">
          <li>Kuramo urugero, urwuzuze (download the template and fill it in):
            {" "}<button className="link" onClick={template}>shg-import-template.xlsx</button></li>
          <li>Hitamo itsinda na dosiye (choose the group and the file).</li>
          <li>Kanda <b>Reba mbere</b>: nta kintu kibikwa (press <b>Check first</b>: nothing is saved).</li>
          <li>Niba nta makosa, kanda <b>Emeza</b> (if there are no mistakes, press <b>Import now</b>).</li>
        </ol>
        <div className="form-grid">
          <label><span>{both(L.group)}</span>
            <select value={shg} onChange={(e) => { setShg(e.target.value); reset(); }}>
              <option value="">-</option>
              {groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
            </select></label>
          <label><span>Dosiye (File, .xlsx)</span>
            <input type="file" accept=".xlsx" onChange={(e) => { setFile(e.target.files[0] || null); reset(); }} /></label>
        </div>
        <div className="row-btns">
          <button className="primary" disabled={busy || !shg || !file} onClick={() => send(true)}>
            {busy && !checked ? "..." : "Reba mbere (Check first)"}
          </button>
          <button className="primary" disabled={busy || !checked} onClick={() => send(false)}>
            Emeza (Import now)
          </button>
        </div>
        {error && <p className="error">{error}</p>}
      </div>

      {result && (
        <div className={`card ${result.ok ? "" : "bad-card"}`}>
          {result.ok ? (
            <p className="ok">{result.dry_run
              ? "Nta makosa. Kanda Emeza kugira ngo bibikwe. (No mistakes. Press Import now to save.)"
              : "Byinjijwe byose. (Everything was imported.)"}</p>
          ) : (
            <p className="error">Nta kintu cyabitswe. Kosora imirongo ikurikira. (Nothing was saved. Fix these rows.)</p>
          )}
          <table className="grid-table compact">
            <tbody>
              <tr><td>Abanyamuryango bashya (New members)</td><td className="num">{result.members_created ?? 0}</td></tr>
              <tr><td>Abari basanzwe (Already in the group)</td><td className="num">{result.members_matched ?? 0}</td></tr>
              <tr><td>Inteko (Meetings)</td><td className="num">{result.meetings ?? 0}</td></tr>
              <tr><td>Ibyanditswe (Money entries)</td><td className="num">{result.entries ?? 0}</td></tr>
              <tr><td>Inguzanyo (Loans)</td><td className="num">{result.loans ?? 0}</td></tr>
            </tbody>
          </table>
          {result.errors?.length > 0 && (
            <table className="grid-table compact err-table">
              <thead><tr><th>Urupapuro (Sheet)</th><th>Umurongo (Row)</th><th>Ikosa (Problem)</th></tr></thead>
              <tbody>
                {result.errors.map((e, i) => <tr key={i}><td>{e.sheet}</td><td>{e.row}</td><td>{e.message}</td></tr>)}
              </tbody>
            </table>
          )}
        </div>
      )}
    </>
  );
}