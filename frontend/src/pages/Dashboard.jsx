import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, errorText } from "../api";
import { useAuth } from "../auth.jsx";
import { useGroups } from "../groups.jsx";
import { L, MONTHS, both, money } from "../labels";
import CashPanel from "./CashPanel.jsx";

const thisYear = new Date().getFullYear();

function Kpi({ label, value, note }) {
  return (
    <div className="kpi">
      <span>{label.rw}<small>{label.en}</small></span>
      <strong>{money(value)}</strong>
      {note && <em>{note}</em>}
    </div>
  );
}

export default function Dashboard() {
  const { user } = useAuth();
  const { groups } = useGroups();
  const isAdmin = user?.role === "ADMIN";
  const [shg, setShg] = useState("");
  const [year, setYear] = useState(thisYear);
  const [month, setMonth] = useState(null);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [pdfBusy, setPdfBusy] = useState(false);

  // A leader with one group always looks at that group.
  useEffect(() => {
    if (!isAdmin && groups.length === 1) setShg(String(groups[0].id));
  }, [isAdmin, groups]);

  const query = () => {
    const q = new URLSearchParams({ year: String(year) });
    if (shg) q.set("shg", shg);
    if (month && !dateFrom && !dateTo) q.set("month", String(month));
    if (dateFrom) q.set("date_from", dateFrom);
    if (dateTo) q.set("date_to", dateTo);
    return q.toString();
  };

  useEffect(() => {
    setError("");
    api.get(`/reports/summary/?${query()}`).then(({ data }) => setData(data)).catch((e) => setError(errorText(e)));
  }, [shg, year, month, dateFrom, dateTo, reloadKey]); // eslint-disable-line

  async function downloadPdf() {
    setPdfBusy(true); setError("");
    try {
      const res = await api.get(`/reports/pdf/?${query()}`, { responseType: "blob" });
      const name = /filename="([^"]+)"/.exec(res.headers["content-disposition"] || "")?.[1] || "shg-report.pdf";
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setPdfBusy(false);
    }
  }

  const t = data?.totals || {};
  const chart = (data?.monthly || []).map((m) => ({
    name: MONTHS[m.month - 1].en, month: m.month,
    Imigabane: m.SHARE, Ingoboka: m.INGOBOKA_IN, Mituweli: m.MUTUELLE,
    Inguzanyo: m.LOAN_ISSUE, Ayishyuwe: m.LOAN_RETURN, Inyungu: m.INTEREST,
  }));
  const multi = (data?.groups?.length || 0) > 1;
  const dim = (m) => (month && m !== month ? 0.35 : 1);

  return (
    <main className="page wide">
      <h1 className="title">{L.dashboard.rw}<small>{L.dashboard.en}{data ? ` - ${data.period.label}` : ""}</small></h1>

      <div className="filters card">
        {(isAdmin || groups.length > 1) ? (
          <label>
            <span>{both(L.group)}</span>
            <select value={shg} onChange={(e) => setShg(e.target.value)}>
              <option value="">{both(L.allGroups)}</option>
              {groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
            </select>
          </label>
        ) : (
          <label><span>{both(L.group)}</span><strong className="fixed">{groups[0]?.name}</strong></label>
        )}
        <label>
          <span>{both(L.year)}</span>
          <select value={year} onChange={(e) => setYear(Number(e.target.value))}>
            {[thisYear, thisYear - 1, thisYear - 2].map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
        </label>
      </div>

      <div className="card filters dates">
        <label><span>Kuva (From)</span>
          <input type="date" value={dateFrom} onChange={(e) => { setDateFrom(e.target.value); setMonth(null); }} /></label>
        <label><span>Kugeza (To)</span>
          <input type="date" value={dateTo} onChange={(e) => { setDateTo(e.target.value); setMonth(null); }} /></label>
        {(dateFrom || dateTo) && (
          <button className="link" onClick={() => { setDateFrom(""); setDateTo(""); }}>Siba amatariki (Clear dates)</button>
        )}
      </div>

      <div className="month-tabs" role="tablist">
        <button className={!month && !dateFrom && !dateTo ? "on" : ""} onClick={() => { setMonth(null); setDateFrom(""); setDateTo(""); }}>{both(L.wholeYear)}</button>
        {MONTHS.map((m, i) => (
          <button key={m.en} className={month === i + 1 ? "on" : ""} onClick={() => { setMonth(i + 1); setDateFrom(""); setDateTo(""); }} title={m.en}>
            {m.rw}<small>{m.en}</small>
          </button>
        ))}
      </div>

      {error && <p className="error">{error}</p>}
      {!data ? <p className="muted">{both(L.loading)}</p> : (
        <>
          <div className="kpis">
            <Kpi label={L.shares} value={t.SHARE} note={`${L.savingsToDate.rw}: ${money(data.savings_to_date)}`} />
            <Kpi label={L.ingoboka} value={t.INGOBOKA_IN} />
            <Kpi label={L.mutuelle} value={t.MUTUELLE} />
            <Kpi label={L.interest} value={t.INTEREST} />
            <Kpi label={L.loansGiven} value={t.LOAN_ISSUE} note={`${L.repaid.rw}: ${money(t.LOAN_RETURN)}`} />
            <Kpi label={L.outstanding} value={data.loans.outstanding}
                 note={data.loans.overdue_count ? `${L.overdue.rw}: ${data.loans.overdue_count} (${money(data.loans.overdue_amount)})` : ""} />
          </div>

          <div className="charts">
            <div className="card chart">
              <h2>Ubwizigame buri kwezi <small>Savings per month, {data.period.year}</small></h2>
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={chart} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="name" fontSize={12} />
                  <YAxis fontSize={11} tickFormatter={(v) => (v >= 1000 ? `${Math.round(v / 1000)}k` : v)} />
                  <Tooltip formatter={(v) => `${money(v)} RWF`} />
                  <Legend />
                  <Bar dataKey="Imigabane" stackId="s" fill="#0f766e">
                    {chart.map((c) => <Cell key={c.month} fillOpacity={dim(c.month)} />)}
                  </Bar>
                  <Bar dataKey="Ingoboka" stackId="s" fill="#14b8a6">
                    {chart.map((c) => <Cell key={c.month} fillOpacity={dim(c.month)} />)}
                  </Bar>
                  <Bar dataKey="Mituweli" stackId="s" fill="#f59e0b">
                    {chart.map((c) => <Cell key={c.month} fillOpacity={dim(c.month)} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="card chart">
              <h2>Inguzanyo buri kwezi <small>Loans per month</small></h2>
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={chart} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="name" fontSize={12} />
                  <YAxis fontSize={11} tickFormatter={(v) => (v >= 1000 ? `${Math.round(v / 1000)}k` : v)} />
                  <Tooltip formatter={(v) => `${money(v)} RWF`} />
                  <Legend />
                  <Bar dataKey="Inguzanyo" fill="#64748b">
                    {chart.map((c) => <Cell key={c.month} fillOpacity={dim(c.month)} />)}
                  </Bar>
                  <Bar dataKey="Ayishyuwe" fill="#0f766e">
                    {chart.map((c) => <Cell key={c.month} fillOpacity={dim(c.month)} />)}
                  </Bar>
                  <Bar dataKey="Inyungu" fill="#f59e0b">
                    {chart.map((c) => <Cell key={c.month} fillOpacity={dim(c.month)} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {multi && (
            <>
              <h2 className="section">{L.groups.rw} <small>{L.groups.en} - {data.period.label}</small></h2>
              <div className="table-wrap">
                <table className="grid-table">
                  <thead><tr>
                    <th>{both(L.group)}</th><th>{L.members.rw}</th><th>{L.shares.rw}</th><th>{L.ingoboka.rw}</th>
                    <th>{L.mutuelle.rw}</th><th>{L.fines.rw}</th><th>{L.interest.rw}</th><th>{L.loansGiven.rw}</th><th>{L.repaid.rw}</th>
                  </tr></thead>
                  <tbody>
                    {data.by_group.map((g) => (
                      <tr key={g.id} className="clickable" onClick={() => setShg(String(g.id))}>
                        <td><strong>{g.name}</strong></td><td>{g.members}</td>
                        <td>{money(g.totals.SHARE)}</td><td>{money(g.totals.INGOBOKA_IN)}</td><td>{money(g.totals.MUTUELLE)}</td>
                        <td>{money(g.totals.FINE_PAYMENT)}</td><td>{money(g.totals.INTEREST)}</td>
                        <td>{money(g.totals.LOAN_ISSUE)}</td><td>{money(g.totals.LOAN_RETURN)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          <h2 className="section">{L.members.rw} <small>{L.members.en} - {data.period.label}</small></h2>
          <div className="table-wrap">
            <table className="grid-table">
              <thead><tr>
                <th>#</th><th>{both(L.name)}</th>{multi && <th>{L.group.rw}</th>}
                <th>{L.shares.rw}<small>count</small></th><th>{L.shares.rw}<small>RWF</small></th>
                <th>{L.ingoboka.rw}</th><th>{L.mutuelle.rw}</th><th>{L.fines.rw}</th><th>{L.interest.rw}</th>
                <th>{L.loansGiven.rw}</th><th>{L.repaid.rw}</th><th>{L.savingsToDate.rw}<small>count</small></th>
              </tr></thead>
              <tbody>
                {data.members.map((m, i) => (
                  <tr key={m.id}>
                    <td className="muted">{i + 1}</td><td>{m.full_name}<small>{m.member_code}</small></td>
                    {multi && <td>{m.shg_name}</td>}
                    <td>{m.shares}</td><td>{money(m.SHARE)}</td><td>{money(m.INGOBOKA_IN)}</td><td>{money(m.MUTUELLE)}</td>
                    <td>{money(m.FINE_PAYMENT)}</td><td>{money(m.INTEREST)}</td><td>{money(m.LOAN_ISSUE)}</td>
                    <td>{money(m.LOAN_RETURN)}</td><td>{m.shares_to_date}</td>
                  </tr>
                ))}
                {!data.members.length && <tr><td colSpan={12} className="muted">{both(L.noMembers)}</td></tr>}
              </tbody>
            </table>
          </div>

          <CashPanel data={data} shg={shg} groups={groups} onChanged={() => setReloadKey((k) => k + 1)} />

          <div className="card report-box">
            <div>
              <h2>{L.report.rw} <small>{L.report.en}</small></h2>
              <p className="muted small">
                {shg ? groups.find((g) => String(g.id) === shg)?.name : L.allGroups.en} - {data.period.label}.
                Irapapurwa neza (print-friendly, black and white).
              </p>
            </div>
            <button className="primary" onClick={downloadPdf} disabled={pdfBusy}>
              {pdfBusy ? "..." : both(L.downloadPdf)}
            </button>
          </div>
        </>
      )}
    </main>
  );
}