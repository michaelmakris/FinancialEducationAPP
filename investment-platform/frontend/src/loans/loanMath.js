// Annuity loans (the usual mortgage / consumer loan): the same payment every month,
// interest charged on what is still owed.

export function monthlyPayment(amount, annualRatePct, years) {
  const n = Math.round(years * 12);
  if (!(amount > 0) || !(n > 0) || annualRatePct == null || !isFinite(annualRatePct)) return null;
  const r = annualRatePct / 100 / 12;
  if (r === 0) return amount / n;
  return (amount * r) / (1 - Math.pow(1 + r, -n));
}

// Month-by-month schedule summed per year: {payment, totalPaid, totalInterest, years: [{year, interest, principal, balance}]}
export function loanPlan(amount, annualRatePct, years) {
  const payment = monthlyPayment(amount, annualRatePct, years);
  if (payment == null) return null;
  const r = annualRatePct / 100 / 12;
  let balance = amount;
  const out = [];
  let totalInterest = 0;
  for (let y = 1; y <= Math.round(years); y++) {
    let interest = 0, principal = 0;
    for (let m = 0; m < 12 && balance > 1e-6; m++) {
      const i = balance * r;
      const p = Math.min(payment - i, balance);
      interest += i;
      principal += p;
      balance -= p;
    }
    totalInterest += interest;
    out.push({ year: y, interest: Math.round(interest), principal: Math.round(principal), balance: Math.max(0, Math.round(balance)) });
  }
  return { payment, totalPaid: amount + totalInterest, totalInterest, years: out };
}
