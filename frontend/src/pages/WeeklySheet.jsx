import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, errorText } from "../api";
import { FINE_REASONS, L, LOAN_STATUS, both, money } from "../labels";

const newId = () =>
  (crypto.randomUUID ? crypto.randomUUID()
    : "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
        const r = (Math.random() * 16) | 0;
        return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
      }));

const num = (v) => (v === "" || v == null ? 0 : Math.max(0, Math.round(Number(v) || 0)));
const EMPTY = { present: null, shares: "", ingoboka: "", mutuelle: "", fine: "", fineReason: "LATE_TO_MEETING",
                returned: "", interest: "", loanId: null, newLoan: "" };

/** A number box sized for typing fast, like a spreadsheet cell. */
function Cell({ value, onChange, recorded, label }) {
  return (
    <td className="cell">
      <input aria-label={label} inputMode="numeric" pattern="[0-9]*" value={value}
             onChange={(e) => onChange(e.target.value.replace(/[^\d]/g, ""))} />
      {recorded > 0 && <small className="recorded">+{money(recorded)}</small>}
    </td>
  );
}

export default function WeeklySheet() {
  const { id } = useParams();
  const [sheet, setSheet] = useState(null);
  const [draft, setDraft] = useState({});
  const [submissionId, setSubmissionId] = useState(newId);
  const [rowErrors, setRowErrors] = useState({});
  const [error, setError] = useState("");
  const [flash, setFlash] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const { data } = await api.get(`/meetings/${id}/sheet/`);
    setSheet(data);
    return data;
  }, [id]);

  useEffect(() => { load().catch((e) => setError(errorText(e))); }, [load]);

  const get = (mid) => ({ ...EMPTY, ...draft[mid] });
  const set = (mid, patch) => setDraft((d) => ({ ...d, [mid]: { ...EMPTY, ...d[mid], ...patch } }));

  const fillAll = (field, value) => setDraft((d) => {
    const next = { ...d };
    for (const r of sheet.rows) {
      const cur = { ...EMPTY, ...next[r.member.id] };
      if (cur[field] === "" || cur[field] === null) next[r.member.id] = { ...cur, [field]: value };
    }
    return next;
  });

  /** Turns the table into the API's weekly-sheet rows, plus the loans to give after saving. */
  const plan = useMemo(() => {
    const rows = [];
    const loans = [];
    if (!sheet) return { rows, loans };
    for (const r of sheet.rows) {
      const d = draft[r.member.id];
      if (!d) continue;
      const v = { ...EMPTY, ...d };
      const loanId = v.loanId ?? r.open_loans[0]?.id ?? null;
      const loan_payments = loanId && (num(v.returned) || num(v.interest))
        ? [{ loan: loanId, returned: num(v.returned), interest: num(v.interest) }] : [];

      // Fine money pays old unpaid fines first (oldest first); anything left is today's new fine.
      let fineLeft = num(v.fine);
      const fine_payments = [];
      for (const f of r.unpaid_fines) {
        if (!fineLeft) break;
        const pay = Math.min(fineLeft, f.remaining);
        fine_payments.push({ fine: f.id, amount: pay });
        fineLeft -= pay;
      }
      const new_fines = fineLeft ? [{ reason: v.fineReason, amount: fineLeft, paid_now: true }] : [];

      const body = { member: r.member.id, present: v.present, shares: num(v.shares), ingoboka: num(v.ingoboka),
                     mutuelle: num(v.mutuelle), loan_payments, fine_payments, new_fines };
      const any = body.shares || body.ingoboka || body.mutuelle || loan_payments.length ||
                  fine_payments.length || new_fines.length || v.present !== null;
      if (any) rows.push({ memberId: r.member.id, body });
      if (num(v.newLoan)) loans.push({ memberId: r.member.id, principal: num(v.newLoan) });
    }
    return { rows, loans };
  }, [draft, sheet]);

  const totals = useMemo(() => {
    const t = { shares: 0, ingoboka: 0, mutuelle: 0, fine: 0, returned: 0, interest: 0, newLoan: 0 };
    for (const d of Object.values(draft)) for (const k of Object.keys(t)) t[k] += num(d[k]);
    return t;
  }, [draft]);

  async function save() {
    if (!plan.rows.length && !plan.loans.length) { setFlash(both(L.nothingToSave)); return; }
    setBusy(true); setError(""); setRowErrors({}); setFlash("");
    const errors = {};
    let savedEntries = 0;
    try {
      if (plan.rows.length) {
        try {
          const { data } = await api.post(`/meetings/${id}/sheet/`, {
            submission_id: submissionId, rows: plan.rows.map((r) => r.body),
          });
          savedEntries = data.saved.transactions;
          setSubmissionId(newId());
        } catch (err) {
          const rows = err.response?.data?.rows;
          if (!rows) throw err;
          for (const [index, fields] of Object.entries(rows)) {
            const memberId = plan.rows[Number(index)]?.memberId;
            if (memberId) errors[memberId] = Object.values(fields).flat();
          }
          setRowErrors(errors);
          setError("Hari ibitagenda - reba imirongo itukura. Nta kintu cyabitswe. (Some rows have errors - see the red rows. Nothing was saved.)");
          return;
        }
      }
      // New loans after the contributions, so today's savings count towards the group's cash.
      const keep = {};
      let loansGiven = 0;
      for (const l of plan.loans) {
        try {
          await api.post("/loans/", { member: l.memberId, principal: l.principal, meeting: Number(id) });
          loansGiven += 1;
        } catch (err) {
          errors[l.memberId] = [`${L.newLoan.en}: ${errorText(err)}`];
          keep[l.memberId] = { ...EMPTY, newLoan: String(l.principal) };
        }
      }
      setDraft(keep);
      setRowErrors(errors);
      await load();
      setFlash(`${both(L.saved)}: ${savedEntries}${loansGiven ? ` · ${L.loans.rw} ${loansGiven}` : ""}`);
      if (Object.keys(errors).length) setError("Inguzanyo zimwe ntizatanzwe - reba imirongo itukura. (Some loans were not given - see the red rows.)");
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  if (error && !sheet) return <main className="page"><p className="error">{error}</p></main>;
  if (!sheet) return <main className="page"><p className="muted">{both(L.loading)}</p></main>;

  const { cycle, meeting, rows } = sheet;
  const hasFines = rows.some((r) => r.unpaid_fines.length);

  return (
    <main className="page wide sheet">
      <h1 className="title">
        {meeting.shg_name} — {meeting.date}
        <small><Link to={`/groups/${meeting.shg}`}>{both(L.meetings)}</Link> · {meeting.shg_code}</small>
      </h1>
      {meeting.is_closed && <p className="warn">{both(L.monthClosed)}</p>}

      {!rows.length ? (
        <div className="card">
          <p>{both(L.noMembers)}</p>
          <Link className="primary-link" to={`/groups/${meeting.shg}/members`}>+ {both(L.addMembers)}</Link>
        </div>
      ) : (
        <>
          <div className="quickfill">
            <button onClick={() => fillAll("present", true)}>{both(L.allPresent)}</button>
            <button onClick={() => fillAll("ingoboka", String(cycle.ingoboka_weekly))}>
              {L.ingoboka.rw} {cycle.ingoboka_weekly} — {both(L.fillAll)}
            </button>
            <button onClick={() => fillAll("mutuelle", String(cycle.mutuelle_weekly))}>
              {L.mutuelle.rw} {cycle.mutuelle_weekly} — {both(L.fillAll)}
            </button>
          </div>

          {flash && <p className="ok">{flash}</p>}
          {error && <p className="error">{error}</p>}

          <div className="table-wrap">
            <table className="grid-table sheet-table">
              <thead>
                <tr>
                  <th className="sticky">{L.name.rw}<small>{L.name.en}</small></th>
                  <th>{L.present.rw}<small>{L.present.en}</small></th>
                  <th>{L.shares.rw}<small>{L.shares.en} (× {cycle.share_price})</small></th>
                  <th>{L.ingoboka.rw}<small>{L.ingoboka.en}</small></th>
                  <th>{L.mutuelle.rw}<small>{L.mutuelle.en}</small></th>
                  <th>{L.fines.rw}<small>{L.fines.en}</small></th>
                  <th>{L.repaid.rw}<small>{L.repaid.en}</small></th>
                  <th>{L.interest.rw}<small>{L.interest.en}</small></th>
                  <th>{L.outstanding.rw}<small>{L.outstanding.en}</small></th>
                  <th>{L.newLoan.rw}<small>{L.newLoan.en}</small></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => {
                  const m = r.member;
                  const v = get(m.id);
                  const rec = r.recorded;
                  const owed = r.open_loans.reduce((s, l) => s + l.outstanding, 0);
                  const unpaid = r.unpaid_fines.reduce((s, f) => s + f.remaining, 0);
                  const errs = rowErrors[m.id];
                  const selectedLoan = v.loanId ?? r.open_loans[0]?.id ?? null;
                  return [
                    <tr key={m.id} className={errs ? "bad" : ""}>
                      <td className="sticky name-cell">
                        <div className="name-wrap">
                          <span className="idx">{i + 1}</span>
                          <span>
                            {m.full_name}
                            <small>
                              {L.shares.rw} {r.to_date.shares}
                              {unpaid > 0 && <em className="chip fine">{L.fine.rw} {money(unpaid)}</em>}
                            </small>
                          </span>
                        </div>
                      </td>
                      <td className="center">
                        <input type="checkbox" aria-label={`${L.present.en} ${m.full_name}`}
                               checked={v.present === true || (v.present === null && r.present === true)}
                               onChange={(e) => set(m.id, { present: e.target.checked })} />
                      </td>
                      <Cell label={`${L.shares.en} ${m.full_name}`} value={v.shares} recorded={rec.shares}
                            onChange={(x) => set(m.id, { shares: x })} />
                      <Cell label={`${L.ingoboka.en} ${m.full_name}`} value={v.ingoboka} recorded={rec.ingoboka}
                            onChange={(x) => set(m.id, { ingoboka: x })} />
                      <Cell label={`${L.mutuelle.en} ${m.full_name}`} value={v.mutuelle} recorded={rec.mutuelle}
                            onChange={(x) => set(m.id, { mutuelle: x })} />
                      <td className="cell">
                        <input aria-label={`${L.fines.en} ${m.full_name}`} inputMode="numeric" value={v.fine}
                               onChange={(e) => set(m.id, { fine: e.target.value.replace(/[^\d]/g, "") })} />
                        {num(v.fine) > unpaid && (
                          <select value={v.fineReason} onChange={(e) => set(m.id, { fineReason: e.target.value })}>
                            {Object.entries(FINE_REASONS).filter(([k]) => k !== "LATE_LOAN" && k !== "OTHER").map(([k, t]) => (
                              <option key={k} value={k}>{t.rw}</option>
                            ))}
                          </select>
                        )}
                        {rec.fines_paid > 0 && <small className="recorded">+{money(rec.fines_paid)}</small>}
                      </td>
                      {r.open_loans.length ? (
                        <>
                          <td className="cell">
                            {r.open_loans.length > 1 && (
                              <select value={selectedLoan} onChange={(e) => set(m.id, { loanId: Number(e.target.value) })}>
                                {r.open_loans.map((l) => <option key={l.id} value={l.id}>{money(l.outstanding)} · {l.due_date}</option>)}
                              </select>
                            )}
                            <input aria-label={`${L.repaid.en} ${m.full_name}`} inputMode="numeric" value={v.returned}
                                   onChange={(e) => set(m.id, { returned: e.target.value.replace(/[^\d]/g, "") })} />
                            {rec.returned > 0 && <small className="recorded">+{money(rec.returned)}</small>}
                          </td>
                          <Cell label={`${L.interest.en} ${m.full_name}`} value={v.interest} recorded={rec.interest}
                                onChange={(x) => set(m.id, { interest: x })} />
                          <td className="owed">
                            {money(owed)}
                            {r.open_loans.map((l) => (
                              <em key={l.id} className={`chip ${l.status.toLowerCase()}`} title={`${L.dueDate.en}: ${l.due_date}`}>
                                {LOAN_STATUS[l.status]?.rw} · {l.due_date}
                              </em>
                            ))}
                          </td>
                        </>
                      ) : (
                        <><td className="na">—</td><td className="na">—</td><td className="na">—</td></>
                      )}
                      <Cell label={`${L.newLoan.en} ${m.full_name}`} value={v.newLoan} recorded={rec.loan_issued}
                            onChange={(x) => set(m.id, { newLoan: x })} />
                    </tr>,
                    errs && (
                      <tr key={`${m.id}-err`} className="err-row">
                        <td colSpan={10}><span className="err-text">{m.full_name}: {errs.join(" · ")}</span></td>
                      </tr>
                    ),
                  ];
                })}
              </tbody>
              <tfoot>
                <tr>
                  <td className="sticky">{L.totals.rw}<small>{L.totals.en}</small></td>
                  <td />
                  <td>{totals.shares} <small>{money(totals.shares * cycle.share_price)}</small></td>
                  <td>{money(totals.ingoboka)}</td>
                  <td>{money(totals.mutuelle)}</td>
                  <td>{money(totals.fine)}</td>
                  <td>{money(totals.returned)}</td>
                  <td>{money(totals.interest)}</td>
                  <td />
                  <td>{money(totals.newLoan)}</td>
                </tr>
              </tfoot>
            </table>
          </div>
          <p className="muted small">
            "+" munsi y'umubare = ibyamaze kubikwa muri iyi nteko. (A "+" under a box = already saved at this meeting;
            what you type now is added to it.)
          </p>
        </>
      )}

      <div className="savebar">
        <button className="primary big" onClick={save} disabled={busy || (!plan.rows.length && !plan.loans.length)}>
          {busy ? both(L.saving) : `${both(L.save)} (${plan.rows.length + plan.loans.length})`}
        </button>
      </div>
    </main>
  );
}
