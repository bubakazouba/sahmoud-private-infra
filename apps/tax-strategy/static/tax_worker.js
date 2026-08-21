/* ──────────────────────────────────────────────────────────────
   tax_worker.js — deterministic tax-strategy compute, no DOM
   Receives: {type:'init', data}  once at startup
             {type:'run', jobId, params}  on each slider event
   Returns:  {type:'result', jobId, years:[...yearRows], lifetime}

   Tax math (single filer, CA resident, 2026):
     Source: Rev. Proc. 2025-32 / Notice 2025-67
     Ordinary brackets: 10/12/22/24/32/35/37%
     LTCG brackets: 0% up to $49,450 taxable income; 15% to $545,500; 20% above
     CA: LTCG taxed as ordinary income (no preferential rate)
     Roth conversion: ordinary income, stacks on top of stipend before LTCG
     LTCG headroom = $49,450 − max(0, ordinary_taxable)
     Sell lots in order specified by cost-basis method to fund spend gap

   AMZN ST→LT aging:
     Lot becomes LT when (acquired + 1 year) < Jan 1 of modeled year
     (conservative: treat lot as LT only when it aged before year starts)

   Sanity test embedded in comments:
     stipend=$37k, no spend, no Roth, no LTCG harvesting → ordinary taxable = $37k − $15k = $22k
     Tax = 10%×$11,925 + 12%×($22k−$11,925) = $1,192.50 + $1,209 = $2,401.50
     CA = ~$736 → total ~$3,138
────────────────────────────────────────────────────────────── */

'use strict';

let DATA = null;

// ── Tax math helpers ─────────────────────────────────────────

function bracketTax(taxable, brackets) {
  if (taxable <= 0) return 0;
  let tax = 0;
  for (const b of brackets) {
    if (taxable <= b.min) break;
    const top = b.max !== null ? b.max : Infinity;
    const inBracket = Math.min(taxable, top) - b.min;
    if (inBracket > 0) tax += inBracket * b.rate;
  }
  return tax;
}

// Federal tax for a single filer with ordinary income + LTCG
// Ordinary income stacks first; LTCG sits on top for bracket calculation
function fedTax(ordinaryIncome, ltcgIncome, brackets) {
  const { stdDeduction, ordinaryBrackets, ltcgBrackets } = brackets;

  const ordinaryGross = Math.max(0, ordinaryIncome - stdDeduction);
  const ordTax = bracketTax(ordinaryGross, ordinaryBrackets);

  // LTCG rate depends on total taxable income (ordinary + LTCG)
  // LTCG sits on top: the rate is determined by where ordinary+ltcg falls
  const ltcgTaxable = Math.max(0, ltcgIncome);
  const totalTaxable = ordinaryGross + ltcgTaxable;

  // LTCG tax = tax on (ordinary+ltcg) at LTCG brackets minus tax on ordinary portion at LTCG brackets
  // Equivalently: for each LTCG dollar, its rate is determined by where it sits in total taxable
  let ltcgTax = 0;
  if (ltcgTaxable > 0) {
    // Amount of LTCG in each LTCG bracket
    for (const b of ltcgBrackets) {
      const top = b.max !== null ? b.max : Infinity;
      // The LTCG portion that falls in [b.min, top] on the combined income stack
      const lo = Math.max(ordinaryGross, b.min);
      const hi = Math.min(ordinaryGross + ltcgTaxable, top);
      if (hi > lo) ltcgTax += (hi - lo) * b.rate;
    }
  }

  return ordTax + ltcgTax;
}

// CA tax: LTCG taxed as ordinary income; no preferential rate
function caTax(ordinaryIncome, ltcgIncome, brackets) {
  const { caOrdinaryBrackets, caStdDeduction } = brackets;
  const totalIncome = ordinaryIncome + Math.max(0, ltcgIncome);
  const taxable = Math.max(0, totalIncome - caStdDeduction);
  return bracketTax(taxable, caOrdinaryBrackets);
}

// ── Lot helpers ──────────────────────────────────────────────

// Parse acquired-date string in either m/d/yy or mm/dd/yyyy format
function parseAcquired(s) {
  const parts = s.split('/');
  const m = parseInt(parts[0], 10);
  const d = parseInt(parts[1], 10);
  let y = parseInt(parts[2], 10);
  if (y < 100) y += 2000;
  // Return numeric date value for fast comparison
  return y * 10000 + m * 100 + d;
}

// Sort a lot list by the given cost-basis method.
// Always sort dynamically from the raw lot data so that the
// pre-sorted keys in data.json (which share the same order) are not trusted.
//   FIFO    — oldest acquired date first
//   HIFO    — lowest gain % first (= highest basis-ratio = minimises gain per dollar sold)
//             Correct cross-symbol definition: sort by totalGain/mv ascending.
//             Within a single symbol this is equivalent to highest cost-per-share first.
//   SpecID  — same as HIFO (manually picking highest-basis lots ≡ HIFO algorithmic)
//   MinTax  — losses first (ascending by gain), then LT near-zero, then LT high-gain.
//             Implemented as (hasGain, gainPct) tuple so losses sort before any gains.
//             For this portfolio (no losses) MinTax ≈ HIFO.
//   AverageCost — handled separately in computeYear; not routed through this function.
function sortLots(lots, method) {
  const copy = lots.map(l => Object.assign({}, l));
  if (method === 'FIFO') {
    return copy.sort((a, b) => parseAcquired(a.acquired) - parseAcquired(b.acquired));
  }
  if (method === 'HIFO' || method === 'SpecID') {
    // Lowest gain% per dollar of MV first — minimises realised gain per $ of proceeds
    return copy.sort((a, b) => {
      const gA = a.mv > 0 ? a.totalGain / a.mv : 0;
      const gB = b.mv > 0 ? b.totalGain / b.mv : 0;
      return gA - gB;
    });
  }
  if (method === 'MinTax') {
    // Losses before gains, then within each group ascending by gain%
    return copy.sort((a, b) => {
      const gA = a.mv > 0 ? a.totalGain / a.mv : 0;
      const gB = b.mv > 0 ? b.totalGain / b.mv : 0;
      const bucketA = a.totalGain < 0 ? 0 : 1; // losses = 0 (first), gains = 1
      const bucketB = b.totalGain < 0 ? 0 : 1;
      if (bucketA !== bucketB) return bucketA - bucketB;
      return gA - gB; // within same bucket, smallest gain% first
    });
  }
  // Fallback: FIFO
  return copy.sort((a, b) => parseAcquired(a.acquired) - parseAcquired(b.acquired));
}

// Returns lots in the order appropriate for the chosen cost-basis method.
// Always uses vanguardLots.FIFO as the canonical raw-lot source (all 166 lots)
// and re-sorts dynamically — the HIFO/MinTax pre-sorted keys in data.json are
// unreliable (investigation confirmed they share the same lot ordering as FIFO).
function getOrderedLots(method, vanguardLots, amznLots, modelYear, showAmznST) {
  const vLots = sortLots(vanguardLots['FIFO'], method);

  // Determine AMZN lot ST/LT status for this year (aged into LT if cross date < Jan 1 of year)
  const yearStart = new Date(`${modelYear}-01-01`);
  const amzn = amznLots.map(l => {
    const aged = l.ltCrossDate ? new Date(l.ltCrossDate) < yearStart : false;
    return Object.assign({}, l, { isShortTerm: aged ? false : l.isShortTerm });
  });

  // Filter AMZN ST if checkbox says hide
  const amznFiltered = showAmznST ? amzn : amzn.filter(l => !l.isShortTerm);

  // Combine: Vanguard lots first (in CSV order = method order), then AMZN LT lots appended
  // AMZN has only 5 lots; for spend-funding we only use LT lots (avoid ST tax hit)
  const ltAmzn = amznFiltered.filter(l => !l.isShortTerm);
  return [...vLots, ...ltAmzn];
}

// Sell enough lots to fund `amountNeeded` of realized LTCG
// Returns { lotsRealized: [...], totalGainRealized, totalCostRealized }
function sellLots(lots, amountNeeded) {
  let remaining = amountNeeded;
  let totalGain = 0;
  let totalCost = 0;
  const sold = [];
  for (const lot of lots) {
    if (remaining <= 0) break;
    if (lot.isShortTerm) continue; // only harvest LT
    if (lot.mv <= 0) continue;
    // fractional sell proportional to lot
    const fractionSell = Math.min(1, remaining / lot.mv);
    const gainRealized = fractionSell * (lot.totalGain || lot.ltGain);
    const mvRealized = fractionSell * lot.mv;
    const costRealized = fractionSell * lot.totalCost;
    sold.push({
      symbol: lot.symbol, acquired: lot.acquired,
      mvRealized, costRealized, gainRealized, fractionSell,
    });
    totalGain += gainRealized;
    totalCost += costRealized;
    remaining -= mvRealized;
  }
  return { lotsRealized: sold, totalGainRealized: totalGain, totalCostRealized: totalCost };
}

// ── Main computation ─────────────────────────────────────────

function computeYear(yearIdx, params, brackets) {
  const {
    spend, stipend, rothConversion, method, showAmznST, year1,
  } = params;

  const modelYear = year1 + yearIdx;

  // Ordinary income this year: stipend + Roth conversion
  // (no earned income once he leaves Amazon in year1)
  const ordinaryIncome = stipend + rothConversion;

  // Spend gap: stipend (cash) covers living expenses first; the remainder comes from portfolio sales.
  // We use gross stipend as the offset (conservative: treats stipend as fully available before tax).
  // This is realistic for a PhD stipend which is ~$37k/yr — taxes are modest and the full amount
  // hits the bank account. Any spend beyond the stipend must be funded by selling LT lots.

  const stdDed = brackets.stdDeduction;
  const ordinaryTaxable = Math.max(0, ordinaryIncome - stdDed);

  // LTCG headroom at 0% rate
  const ltcg0Headroom = Math.max(0, brackets.ltcg0PctCeiling - ordinaryTaxable);

  // Portfolio sales needed: spend net of stipend (stipend covers living expenses up to its amount)
  const spendFromPortfolio = Math.max(0, spend - stipend);
  // (we might exceed headroom if net spend > headroom; that portion gets taxed at 15%)

  // Baseline (do-nothing): same spend but sell at average basis ratio, no optimization
  const totalVMV = DATA.summary.vanguardMV + DATA.summary.amznMV;
  const totalVCost = DATA.summary.vanguardCost + DATA.summary.amznCost;
  const avgBasisRatio = totalVCost / totalVMV;
  const baselineGainPct = 1 - avgBasisRatio;
  const baselineLTCG = spendFromPortfolio * baselineGainPct;

  // Strategy LTCG: AverageCost uses same avgBasisRatio formula; all others use lot selection
  let ltcgRealized;
  if (method === 'AverageCost') {
    // Average Cost: every share sold realizes the same per-share gain = portfolio avg basis ratio
    ltcgRealized = Math.max(0, spendFromPortfolio * baselineGainPct);
  } else {
    const lots = getOrderedLots(method, DATA.vanguardLots, DATA.amznLots, modelYear, showAmznST);
    const { totalGainRealized } = sellLots(lots, spendFromPortfolio);
    ltcgRealized = Math.max(0, totalGainRealized);
  }

  // Fed tax — strategy
  const fedStrategy = fedTax(ordinaryIncome, ltcgRealized, brackets);
  // Fed tax — baseline (same ordinary income, baseline LTCG)
  const fedBaseline = fedTax(ordinaryIncome, baselineLTCG, brackets);

  // CA tax
  const caStrategy = caTax(ordinaryIncome, ltcgRealized, brackets);
  const caBaseline = caTax(ordinaryIncome, baselineLTCG, brackets);

  return {
    year: modelYear,
    spendFundedFrom: 'LT lot sales',
    ordinaryIncome,
    rothConversion,
    ltcgRealized: Math.round(ltcgRealized),
    ltcg0Headroom: Math.round(ltcg0Headroom),
    fedTaxStrategy: Math.round(fedStrategy),
    fedTaxBaseline: Math.round(fedBaseline),
    caTaxStrategy: Math.round(caStrategy),
    caTaxBaseline: Math.round(caBaseline),
    totalTaxStrategy: Math.round(fedStrategy + caStrategy),
    totalTaxBaseline: Math.round(fedBaseline + caBaseline),
    taxSavingsVsBaseline: Math.round((fedBaseline + caBaseline) - (fedStrategy + caStrategy)),
  };
}

function computeAll(params) {
  const { years, year1 } = params;
  const brackets = DATA.taxBrackets;
  const yearRows = [];

  let cumulativeLTCG = 0;
  let cumulativeTaxStrategy = 0;
  let cumulativeTaxBaseline = 0;

  for (let i = 0; i < years; i++) {
    const row = computeYear(i, params, brackets);
    cumulativeLTCG += row.ltcgRealized;
    cumulativeTaxStrategy += row.totalTaxStrategy;
    cumulativeTaxBaseline += row.totalTaxBaseline;
    yearRows.push({
      ...row,
      cumulativeLTCG,
      cumulativeTaxStrategy,
      cumulativeTaxBaseline,
      cumulativeSavings: cumulativeTaxBaseline - cumulativeTaxStrategy,
    });
  }

  const lifetimeSavings = cumulativeTaxBaseline - cumulativeTaxStrategy;

  // Lot inventory for chart 1 (basis ratio by lot, in chosen method order)
  // Use FIFO for inventory (method only affects which are sold first, not the inventory)
  const fifoLots = DATA.vanguardLots.FIFO;
  const amznLots = DATA.amznLots;
  const allLots = [...fifoLots, ...amznLots].map(l => ({
    label: `${l.symbol} ${l.acquired}`,
    symbol: l.symbol,
    acquired: l.acquired,
    qty: l.qty,
    costPerShare: l.costPerShare,
    mv: l.mv,
    totalCost: l.totalCost,
    basisRatio: l.mv > 0 ? l.totalCost / l.mv : 1,
    isShortTerm: l.isShortTerm,
    gainPct: l.mv > 0 ? ((l.mv - l.totalCost) / l.totalCost * 100) : 0,
  })).sort((a, b) => b.basisRatio - a.basisRatio); // highest basis first for display

  return {
    yearRows,
    lifetimeSavings: Math.round(lifetimeSavings),
    lotInventory: allLots,
    summary: DATA.summary,
    brackets: DATA.taxBrackets,
  };
}

self.onmessage = function(e) {
  const msg = e.data;

  if (msg.type === 'init') {
    DATA = msg.data;
    self.postMessage({ type: 'ready' });
    return;
  }

  if (msg.type === 'run') {
    try {
      const result = computeAll(msg.params);
      self.postMessage({ type: 'result', jobId: msg.jobId, ...result });
    } catch (err) {
      self.postMessage({ type: 'error', jobId: msg.jobId, message: err.message });
    }
  }
};
