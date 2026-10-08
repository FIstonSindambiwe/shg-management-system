import { useEffect, useState } from "react";
import { api, errorText } from "../api";
import { useAuth } from "../auth.jsx";
import { useGroups } from "../groups.jsx";
import { L, MONTHS, both, money } from "../labels";

const now = new Date();
const thisYear = now.getFullYear();
const iso = (d) => d.toISOString().slice(0, 10);

/** Choose a group and a period, see the main figures, download the print-friendly PDF. */
export default function Reports() {
  const { user } = useAuth();
  const { groups } = useGroups();
  const isAdmin = user?.role === "ADMIN";
  const [shg, setShg] = useState("");
  const [year, setYear] = useState(thisYear);
  const [month, setMonth] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [format, setFormat] = useState("pdf");

  useEffect(() => {
    if (!isAdmin && groups.length === 1) setShg(String(groups[0].id));
  }, [isAdmin, groups]);

  const query = () => {
    const q = new URLSearchParams({ year: String(year) });
    if (shg) q.set("shg", shg);
    if (dateFrom || dateTo) {
      if (dateFrom) q.set("date_from", dateFrom);
      if (dateTo) q.set("date_to", dateTo);
    } else if (month) q.set("month", month);
    return q.toString();
  };

  useEffect(() => {
    setError("");
    api.get(`/reports/summary/?${query()}`).then(({ data }) => setData(data)).catch((e) => setError(errorText(e)));
  }, [shg, year, month, dateFrom, dateTo]); // eslint-disable-line

  function preset(kind) {
    const y = now.getFullYear(), m = now.getMonth();
    if (kind === "this") { setYear(y); setMonth(String(m + 1)); }
    if (kind === "last") { const d = new Date(y, m - 1, 1); setYear(d.getFullYear()); setMonth(String(d.getMonth() + 1)); }
    if (kind === "year") { setYear(y); setMonth(""); }
    setDateFrom(""); setDateTo("");
  }

  async function download() {
    setBusy(true); setError("");
    try {
      const res = await api.get(`/reports/${format}/?${query()}`, { responseType: "blob" });
      const name = /filename="([^"]+)"/.exec(res.headers["content-disposition"] || "")?.[1] || `shg-report.${format}`;
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  const t = data?.totals || {};
  const c = data?.cash?.to_date;
  const rows = data ? [
    ["Imigabane", "Shares bought", t.SHARE], ["Ingoboka", "Social fund", t.INGOBOKA_IN],
    ["Mituweli", "Mutuelle", t.MUTUELLE], ["Ibihano", "Fines paid", t.FINE_PAYMENT],
    ["Inyungu", "Interest", t.INTEREST], ["Inguzanyo zatanzwe", "Loans given", t.LOAN_ISSUE],
    ["Ayishyuwe", "Loans returned", t.LOAN_RETURN], ["Andi mafaranga yinjiye", "Other money in", t.OTHER_INCOME],
    ["Ibyakoreshejwe", "Money spent", t.EXPENSE], ["Byajyanywe kuri banki", "Taken to the bank", t.BANK_DEPOSIT],
  ] : [];

  return (
    <main className="page wide">
      <h1 className="title">{L.report.rw}<small>{L.report.en}{data ? ` - ${data.period.label}` : ""}</small></h1>

      <div className="card report-filters">
        {(isAdmin || groups.length > 1) ? (
          <label><span>{both(L.group)}</span>
            <select value={shg} onChange={(e) => setShg(e.target.value)}>
              <option value="">{both(L.allGroups)}</option>
              {groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
            </select></label>
        ) : (
          <label><span>{both(L.group)}</span><strong className="fixed">{groups[0]?.name}</strong></label>
        )}
        <label><span>{both(L.year)}</span>
          <select value={year} onChange={(e) => { setYear(Number(e.target.value)); setDateFrom(""); setDateTo(""); }}>
            {[thisYear, thisYear - 1, thisYear - 2].map((y) => <option key={y} value={y}>{y}</option>)}
          </select></label>
        <label><span>Ukwezi (Month)</span>
          <select value={month} onChange={(e) => { setMonth(e.target.value); setDateFrom(""); setDateTo(""); }}>
            <option value="">{both(L.wholeYear)}</option>
            {MONTHS.map((m, i) => <option key={m.en} value={i + 1}>{m.rw} ({m.en})</option>)}
          </select></label>
        <label><span>Kuva (From)</span>
          <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} /></label>
        <label><span>Kugeza (To)</span>
          <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} /></label>
      </div>

      <div className="presets">
        <button onClick={() => preset("this")}>Uku kwezi (This month)</button>
        <button onClick={() => preset("last")}>Ukwezi gushize (Last month)</button>
        <button onClick={() => preset("year")}>Uyu mwaka (This year)</button>
        {(dateFrom || dateTo) && <button onClick={() => { setDateFrom(""); setDateTo(""); }}>Siba amatariki (Clear dates)</button>}
      </div>
      {(dateFrom || dateTo) && <p className="muted small">Amatariki arusha ukwezi (the dates are used instead of the month).</p>}

      {error && <p className="error">{error}</p>}
      {!data ? <p className="muted">{both(L.loading)}</p> : (
        <div className="report-layout">
          <div className="card">
            <h2>Ibizaba muri raporo <small>What the report will show - {data.period.label}</small></h2>
            <table className="grid-table">
              <tbody>
                {rows.map(([rw, en, v]) => (
                  <tr key={rw}><td>{rw}<small>{en}</small></td><td className="num">{money(v)}</td></tr>
                ))}
                <tr className="final-row"><td>Asigaye mu ntoki<small>Cash still in hand, up to the end date</small></td>
                  <td className="num">{money(c?.in_hand)}</td></tr>
              </tbody>
            </table>
          </div>
          <div className="card download-card">
            <h2>Kuramo raporo <small>Download the report</small></h2>
            <div className="format-pick" role="radiogroup">
              <button className={format === "pdf" ? "on" : ""} onClick={() => setFormat("pdf")}>
                PDF<small>Gucapa (to print)</small></button>
              <button className={format === "xlsx" ? "on" : ""} onClick={() => setFormat("xlsx")}>
                Excel<small>Gukomeza kubara (to work with)</small></button>
            </div>
            <p className="muted small">
              {shg ? groups.find((g) => String(g.id) === shg)?.name : L.allGroups.en} - {data.period.label}
              <br />{data.members.length} {L.members.rw.toLowerCase()} - irapapurwa neza (print-friendly, black and white).
            </p>
            <button className="primary big" onClick={download} disabled={busy}>
              {busy ? "..." : `Kuramo ${format === "pdf" ? "PDF" : "Excel"} (Download ${format === "pdf" ? "PDF" : "Excel"})`}
            </button>
          </div>
        </div>
      )}
    </main>
  );
}