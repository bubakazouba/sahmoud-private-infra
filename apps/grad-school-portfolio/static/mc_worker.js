/* ──────────────────────────────────────────────────────────
   mc_worker.js — pure MC compute, no DOM access
   Receives: {type:'init', returns, years} once at startup,
             {type:'run', jobId, params} on each slider event
   Returns:  {jobId, binCounts, binMin, BIN,
              samplePaths, percentilePaths,
              pct5,pct25,pct50,pct75,pct95,
              probabilities, decadeReplay}
   ────────────────────────────────────────────────────────── */

'use strict';

let realReturns = null;
let years = null;
const PATHS_TO_STORE = 50;
const BIN = 250_000;

function percentile(sorted, p) {
  const idx = p * (sorted.length - 1);
  const lo = Math.floor(idx);
  const hi = Math.ceil(idx);
  if (lo === hi) return sorted[lo];
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (idx - lo);
}

function simulate(p) {
  const { start, masters, phd, spend, stipend, nSims, mode, blockSize } = p;
  const horizon = masters + phd;
  const n = realReturns.length;

  // yearlyPercentiles: for each year store sorted values so we can compute pctl
  // We accumulate per-year accumulators (sorted inline after sim)
  const yearlyAccum = Array.from({ length: horizon + 1 }, () => new Float64Array(nSims));

  const endings = new Float64Array(nSims);
  const samplePaths = [];

  for (let i = 0; i < nSims; i++) {
    yearlyAccum[0][i] = start;

    let yearReturns;
    if (mode === 'block') {
      yearReturns = [];
      while (yearReturns.length < horizon) {
        const needed = horizon - yearReturns.length;
        const bs = Math.min(blockSize, needed, n);
        const maxStart = n - bs;
        const startIdx = Math.floor(Math.random() * (maxStart + 1));
        for (let k = 0; k < bs; k++) yearReturns.push(realReturns[startIdx + k]);
      }
      yearReturns = yearReturns.slice(0, horizon);
    } else {
      yearReturns = new Float64Array(horizon);
      for (let y = 0; y < horizon; y++) yearReturns[y] = realReturns[Math.floor(Math.random() * n)];
    }

    let bal = start;
    const storePath = i < PATHS_TO_STORE;
    const pathArr = storePath ? [bal] : null;

    for (let y = 0; y < horizon; y++) {
      bal *= 1 + yearReturns[y];
      bal -= spend;
      if (y >= masters) bal += stipend;
      yearlyAccum[y + 1][i] = bal;
      if (storePath) pathArr.push(bal);
    }

    endings[i] = bal;
    if (storePath) samplePaths.push(pathArr);
  }

  return { endings, yearlyAccum, samplePaths, horizon };
}

function computeAll(p) {
  const { start, masters, phd, spend, stipend } = p;
  const horizon = masters + phd;
  const n = realReturns.length;

  if (horizon === 0) {
    const endings = new Float64Array(p.nSims).fill(start);
    const sorted = Float64Array.from(endings).sort();
    const pct50 = start;
    const samplePaths = Array.from({ length: PATHS_TO_STORE }, () => [start]);

    // Histogram
    const { binCounts, binMin } = makeHistogram(endings);

    // Probabilities
    const probabilities = computeProbabilities(sorted, start);

    // Decade replay (trivial case)
    const decadeReplay = [];

    // Percentile paths — just a single year-0 point
    const percentilePaths = {
      pct5: [start], pct25: [start], pct50: [start], pct75: [start], pct95: [start],
    };

    return {
      binCounts, binMin, BIN,
      samplePaths,
      percentilePaths,
      pct5: start, pct25: start, pct50: start, pct75: start, pct95: start,
      probabilities,
      decadeReplay,
      horizon,
    };
  }

  const { endings, yearlyAccum, samplePaths } = simulate(p);

  // Sort endings
  const sorted = Float64Array.from(endings).sort();
  const pct5 = percentile(sorted, 0.05);
  const pct25 = percentile(sorted, 0.25);
  const pct50 = percentile(sorted, 0.50);
  const pct75 = percentile(sorted, 0.75);
  const pct95 = percentile(sorted, 0.95);

  // Histogram bin counts
  const { binCounts, binMin } = makeHistogram(endings);

  // Percentile paths — sort each year's column and extract 5 percentiles
  const percentilePaths = {
    pct5: [], pct25: [], pct50: [], pct75: [], pct95: [],
  };
  for (let yr = 0; yr <= horizon; yr++) {
    const col = Float64Array.from(yearlyAccum[yr]).sort();
    percentilePaths.pct5.push(percentile(col, 0.05));
    percentilePaths.pct25.push(percentile(col, 0.25));
    percentilePaths.pct50.push(percentile(col, 0.50));
    percentilePaths.pct75.push(percentile(col, 0.75));
    percentilePaths.pct95.push(percentile(col, 0.95));
  }

  // Probabilities
  const probabilities = computeProbabilities(sorted, start);

  // Decade replay
  const decadeReplay = computeDecadeReplay(p, horizon, n);

  return {
    binCounts, binMin, BIN,
    samplePaths,
    percentilePaths,
    pct5, pct25, pct50, pct75, pct95,
    probabilities,
    decadeReplay,
    horizon,
  };
}

function makeHistogram(endings) {
  let minV = endings[0], maxV = endings[0];
  for (let i = 1; i < endings.length; i++) {
    if (endings[i] < minV) minV = endings[i];
    if (endings[i] > maxV) maxV = endings[i];
  }
  const binMin = Math.floor(minV / BIN) * BIN;
  const binMax = Math.ceil(maxV / BIN) * BIN;
  const nBins = Math.max(1, Math.round((binMax - binMin) / BIN));
  const binCounts = new Array(nBins).fill(0);
  for (let i = 0; i < endings.length; i++) {
    const idx = Math.min(Math.floor((endings[i] - binMin) / BIN), nBins - 1);
    if (idx >= 0) binCounts[idx]++;
  }
  return { binCounts, binMin };
}

function computeProbabilities(sorted, start) {
  const N = sorted.length;
  let ltStart = 0, lt1M = 0, lt500K = 0, ruin = 0, gtStart = 0, gt2x = 0;
  for (let i = 0; i < N; i++) {
    const v = sorted[i];
    if (v < start) ltStart++;
    if (v < 1_000_000) lt1M++;
    if (v < 500_000) lt500K++;
    if (v <= 0) ruin++;
    if (v > start) gtStart++;
    if (v > 2 * start) gt2x++;
  }
  return {
    ltStart: ltStart / N,
    lt1M: lt1M / N,
    lt500K: lt500K / N,
    ruin: ruin / N,
    gtStart: gtStart / N,
    gt2x: gt2x / N,
  };
}

function computeDecadeReplay(p, horizon, n) {
  const { start, masters, spend, stipend } = p;
  const results = [];
  for (let s = 0; s <= n - horizon; s++) {
    let bal = start;
    let peak = start;
    let maxDrawdown = 0;
    for (let y = 0; y < horizon; y++) {
      bal *= 1 + realReturns[s + y];
      bal -= spend;
      if (y >= masters) bal += stipend;
      if (bal > peak) peak = bal;
      const dd = peak > 0 ? (bal - peak) / peak : 0;
      if (dd < maxDrawdown) maxDrawdown = dd;
    }
    results.push({ startYear: years[s], endYear: years[s + horizon - 1], ending: bal, maxDrawdown });
  }
  return results;
}

self.onmessage = function (e) {
  const msg = e.data;

  if (msg.type === 'init') {
    realReturns = msg.returns;
    years = msg.years;
    self.postMessage({ type: 'ready' });
    return;
  }

  if (msg.type === 'run') {
    const result = computeAll(msg.params);
    self.postMessage({ type: 'result', jobId: msg.jobId, ...result });
  }
};
