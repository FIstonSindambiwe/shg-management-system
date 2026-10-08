import { useState } from "react";
import { api, errorText } from "../api";
import { money } from "../labels";

const today = () => new Date().toISOString().slice(0, 10);

const IN_ROWS = [
  ["SHARE", "Imigabane", "Shares"], ["INGOBOKA_IN", "Ingoboka", "Social fund"],
  ["FINE_PAYMENT", "Ibihano", "Fines"], ["INTEREST", "Inyungu", "Interest"],
  ["LOAN_RETURN", "Ayishyuwe", "Loans returned"], ["OTHER_INCOME", "Andi mafaranga yinjiye", "Other money in"],
];
const OUT_ROWS = [
  ["LOAN_ISSUE", "Inguzanyo zatanzwe", "Loans given"], ["INGOBOKA_OUT", "Ingoboka yatanzwe", "Social fund paid out"],
  ["EXPENSE", "Ibyakoreshejwe", "Money spent"],
];
const KINDS = {
  OTHER_INCOME: { rw: "Andi mafaranga yinjiye", en: "Other money in" },
  EXPENSE: { rw: "Amafaranga yakoreshejwe", en: "Money spent" },
  BANK_DEPOSIT: { rw: "Kujyana kuri banki", en: "Taken to the bank" },
  INGOBOKA_OUT: { rw: "Ingoboka yatanzwe", en: "Social fund paid out" },
};
const CATEGORIES = [
  ["MATERIALS", "Ibikoresho (Materials)"], ["MEETING", "Inama (Meeting)"], ["TRANSPORT", "Urugendo (Transport)"],
  ["ADMIN", "Ubuyobozi (Administration)"], ["OTHER", "Ibindi (Other)"],
];
const EMPTY = { type: "OTHER_INCOME", amount: "", date: today(), description: "", expense_category: "MATERIALS", carried_by: "" };

function Row({ label, en, a, b, cls = "" }) {
  return (
    <tr className={cls}>
      <td>{label}<small>{en}</small></td>
      <td className="num">{money(a)}</td>
      <td className="num">{money(b)}</td>
    </tr>
  );
}

export default function CashPanel({ data, shg, groups, onChanged }) {
  const [form, setForm] = useState(EMPTY);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const cash = data.cash;
  if (!cash) return null;
  const P = cash.period, D = cash.to_date;
  const multi = data.groups.length > 1;
  const groupName = groups.find((g) => String(g.id) === String(shg))?.name;

  async function save(e) {
    e.preventDefault();
    setBusy(true); setMsg(null);
    try {
      const body = { shg: Number(shg), type: form.type, amount: Number(form.amount), date: form.date,
                     description: form.description.trim(), carried_by: form.carried_by.trim() };
      if (form.type === "EXPENSE") body.expense_category = form.expense_category;
      await api.post("/transactions/", body);
      setForm({ ...EMPTY, type: form.type, date: form.date });
      setMsg({ kind: "ok", t: "Byabitswe (Saved)" });
      onChanged();
    } catch (err) {
      setMsg({ kind: "error", t: errorText(err) });
    } finally {
      setBusy(false);
    }
  }

  async function undo(entry) {
    const reason = window.prompt(`Siba iyi nyandiko? (Undo this entry?)\n${KINDS[entry.type]?.rw}: ${money(entry.amount)}\n\nImpamvu (Reason):`);
    if (!reason) return;
    try {
      await api.post(`/transactions/${entry.id}/reverse/`, { reason });
      onChanged();
    } catch (err) {
      setMsg({ kind: "error", t: errorText(err) });
    }
  }

  return (
    <div className="card cash">
      <h2>Imari y'itsinda <small>Group cash - {data.period.label}</small></h2>
      <div className="table-wrap">
        <table className="grid-table cash-table">
          <thead><tr><th /><th className="num">Muri iki gihe<small>This period</small></th>
            <th className="num">Kugeza ubu<small>Up to the end date</small></th></tr></thead>
          <tbody>
            {IN_ROWS.map(([k, rw, en]) => <Row key={k} label={`+ ${rw}`} en={en} a={P.in[k]} b={D.in[k]} />)}
            <Row label="Byinjiye byose" en="Total in" a={P.total_in} b={D.total_in} cls="sub" />
            {OUT_ROWS.map(([k, rw, en]) => <Row key={k} label={`- ${rw}`} en={en} a={P.out[k]} b={D.out[k]} />)}
            <Row label="Byasohotse byose" en="Total out" a={P.total_out} b={D.total_out} cls="sub" />
            <Row label="Igiteranyo" en="In minus out" a={P.net} b={D.net} cls="sub" />
            <Row label="- Byajyanywe kuri banki" en="Taken to the bank" a={P.bank_deposits} b={D.bank_deposits} />
            <Row label="Asigaye mu ntoki" en="Cash still in hand" a={P.in_hand} b={D.in_hand} cls="final" />
          </tbody>
        </table>
      </div>
      <p className="muted small">
        Mituweli ibitswe ukwayo, ntibarwa hano (Mutuelle is kept apart and not counted here):
        {" "}{money(P.mutuelle)} muri iki gihe / {money(D.mutuelle)} kugeza ubu.
      </p>

      <h3>Andika amafaranga <small>Record money</small></h3>
      {!shg ? (
        <p className="muted">Hitamo itsinda rimwe hejuru (Choose one group in the filter above first).</p>
      ) : (
        <form className="cash-form" onSubmit={save}>
          <label><span>Ubwoko (Type)</span>
            <select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
              {["OTHER_INCOME", "EXPENSE", "BANK_DEPOSIT"].map((k) => <option key={k} value={k}>{KINDS[k].rw} ({KINDS[k].en})</option>)}
            </select></label>
          <label><span>Amafaranga (Amount, RWF)</span>
            <input inputMode="numeric" value={form.amount}
                   onChange={(e) => setForm({ ...form, amount: e.target.value.replace(/[^\d]/g, "") })} /></label>
          <label><span>Itariki (Date)</span>
            <input type="date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} /></label>
          {form.type === "EXPENSE" && (
            <label><span>Icyo yakoreshejwe (Spent on)</span>
              <select value={form.expense_category} onChange={(e) => setForm({ ...form, expense_category: e.target.value })}>
                {CATEGORIES.map(([k, t]) => <option key={k} value={k}>{t}</option>)}
              </select></label>
          )}
          {form.type === "BANK_DEPOSIT" && (
            <label><span>Uwayajyanye kuri banki (Person taking it to the bank)</span>
              <input value={form.carried_by} onChange={(e) => setForm({ ...form, carried_by: e.target.value })}
                     placeholder="e.g. MUKAMANA Grace" /></label>
          )}
          <label className="wide"><span>Ibisobanuro (Details{form.type === "OTHER_INCOME" ? ", required" : ""})</span>
            <input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })}
                   placeholder={form.type === "BANK_DEPOSIT" ? "Banki, nomero ya fishi (bank, slip number)" : ""} /></label>
          <button className="primary" disabled={busy || !form.amount
            || (form.type === "BANK_DEPOSIT" && !form.carried_by.trim())
            || (form.type === "OTHER_INCOME" && !form.description.trim())}>
            {busy ? "..." : `Bika (Save) - ${groupName || ""}`}
          </button>
        </form>
      )}
      {msg && <p className={msg.kind}>{msg.t}</p>}

      {cash.entries.length > 0 && (
        <div className="table-wrap">
          <table className="grid-table">
            <thead><tr>
              <th>Itariki<small>Date</small></th>{multi && <th>Itsinda<small>Group</small></th>}
              <th>Ubwoko<small>Type</small></th><th>Ibisobanuro<small>Details</small></th>
              <th>Uwayajyanye<small>Taken by</small></th><th className="num">Amafaranga<small>RWF</small></th><th />
            </tr></thead>
            <tbody>
              {cash.entries.map((e) => (
                <tr key={e.id}>
                  <td>{e.date}</td>{multi && <td>{e.shg_name}</td>}
                  <td>{KINDS[e.type]?.rw}<small>{KINDS[e.type]?.en}</small></td>
                  <td>{e.description || e.member || "-"}<small>{e.recorded_by}</small></td>
                  <td>{e.carried_by || "-"}</td>
                  <td className="num">{e.type === "OTHER_INCOME" ? "+" : "-"}{money(e.amount)}</td>
                  <td><button className="link" onClick={() => undo(e)}>Siba (Undo)</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}