/* ──────────────────────────────────────────────────────────
   Tax Strategy Sandbox — app.js
   Worker: tax_worker.js (deterministic, no MC)
   Data: data.json (166 Vanguard lots + 5 AMZN lots, bundled)
   ────────────────────────────────────────────────────────── */

'use strict';

// ── Helpers ──────────────────────────────────────────────────
const fmt$ = (v) =>
  (v < 0 ? '-$' : '$') + Math.abs(Math.round(v)).toLocaleString('en-US');
const fmtPct = (v) => v.toFixed(1) + '%';
const fmtK = (v) => {
  const abs = Math.abs(v);
  if (abs >= 1e6) return (v < 0 ? '-' : '') + '$' + (abs / 1e6).toFixed(2) + 'M';
  if (abs >= 1000) return (v < 0 ? '-' : '') + '$' + (abs / 1000).toFixed(0) + 'k';
  return fmt$(v);
};

// ── State ────────────────────────────────────────────────────
let DATA = null;
let charts = {};
let worker = null;
let workerReady = false;
let jobCounter = 0;
let latestJobId = -1;
let pendingRaf = null;
let pendingResult = null;
let computingTimer = null;

// ── Worker setup ─────────────────────────────────────────────
function initWorker() {
  worker = new Worker('tax_worker.js');
  worker.onmessage = function(e) {
    const msg = e.data;
    if (msg.type === 'ready') {
      workerReady = true;
      runAndRender();
      return;
    }
    if (msg.type === 'result') {
      if (msg.jobId !== latestJobId) return;
      pendingResult = msg;
      if (pendingRaf) cancelAnimationFrame(pendingRaf);
      pendingRaf = requestAnimationFrame(applyResult);
    }
    if (msg.type === 'error') {
      console.error('tax_worker error:', msg.message);
      hideIndicator();
    }
  };
  worker.onerror = (err) => { console.error('worker error:', err); hideIndicator(); };
}

function postJob(params) {
  if (!workerReady) return;
  const jobId = ++jobCounter;
  latestJobId = jobId;
  showIndicator();
  worker.postMessage({ type: 'run', jobId, params });
}

// ── Load data ─────────────────────────────────────────────────
fetch('data.json')
  .then((r) => r.json())
  .then((d) => {
    DATA = d;
    console.log('Loaded data:', d.summary.vanguardLotsCount, 'Vanguard lots, MV=', d.summary.vanguardMV);

    // Populate derived bar with static data
    document.getElementById('d-vmv').textContent = fmtK(d.summary.vanguardMV);
    document.getElementById('d-amzn-mv').textContent = fmtK(d.summary.amznMV);
    document.getElementById('d-brokerage-mv').textContent = fmtK(d.summary.totalBrokerageMV);
    document.getElementById('lot-count').textContent = d.summary.vanguardLotsCount + ' Vanguard + ' + d.summary.amznLotsCount + ' AMZN';

    initCharts();
    bindControls();
    initWorker();
    worker.postMessage({ type: 'init', data: d });
  })
  .catch((e) => {
    document.body.innerHTML += '<p style="color:#f85149;padding:24px">Error loading data.json: ' + e + '</p>';
  });

// ── Indicator ────────────────────────────────────────────────
function showIndicator() {
  clearTimeout(computingTimer);
  computingTimer = setTimeout(() => {
    const el = document.getElementById('loading-indicator');
    if (el) el.style.display = 'flex';
  }, 60);
}
function hideIndicator() {
  clearTimeout(computingTimer);
  const el = document.getElementById('loading-indicator');
  if (el) el.style.display = 'none';
}

// ── Bind controls ─────────────────────────────────────────────
function bindControls() {
  ['sl-spend', 'sl-years', 'sl-stipend', 'sl-roth', 'sl-year1'].forEach((id) => {
    document.getElementById(id).addEventListener('input', () => {
      updateLabels();
      scheduleSim();
    });
  });
  document.querySelectorAll('input[name="method"]').forEach((r) =>
    r.addEventListener('change', () => {
      const note = document.getElementById('avg-cost-note');
      if (note) note.style.display = r.value === 'AverageCost' && r.checked ? 'block' : (note.style.display);
      // recalculate note visibility based on current selection
      const sel = document.querySelector('input[name="method"]:checked');
      if (note) note.style.display = sel && sel.value === 'AverageCost' ? 'block' : 'none';
      scheduleSim();
    })
  );
  document.getElementById('cb-show-amzn-st').addEventListener('change', () => scheduleSim());

  updateLabels();
}

let debounceTimer = null;
function scheduleSim() {
  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(runAndRender, 30);
}

function getParams() {
  const spend = +document.getElementById('sl-spend').value;
  const years = +document.getElementById('sl-years').value;
  const stipend = +document.getElementById('sl-stipend').value;
  const rothConversion = +document.getElementById('sl-roth').value;
  const year1 = +document.getElementById('sl-year1').value;
  const method = document.querySelector('input[name="method"]:checked').value;
  const showAmznST = document.getElementById('cb-show-amzn-st').checked;
  return { spend, years, stipend, rothConversion, year1, method, showAmznST };
}

function updateLabels() {
  const p = getParams();
  document.getElementById('lbl-spend').textContent = fmt$(p.spend);
  document.getElementById('lbl-years').textContent = p.years;
  document.getElementById('lbl-stipend').textContent = fmt$(p.stipend);
  document.getElementById('lbl-roth').textContent = fmt$(p.rothConversion);
  document.getElementById('lbl-year1').textContent = p.year1;
  document.getElementById('d-endyr').textContent = p.year1 + p.years - 1;

  // Compute 0%-LTCG headroom for derived bar
  if (DATA) {
    const std = DATA.taxBrackets.stdDeduction;
    const ordTaxable = Math.max(0, p.stipend + p.rothConversion - std);
    const headroom = Math.max(0, DATA.taxBrackets.ltcg0PctCeiling - ordTaxable);
    document.getElementById('d-headroom').textContent = fmt$(headroom);
    document.getElementById('d-ord-taxable').textContent = fmt$(ordTaxable);
  }
}

function runAndRender() {
  if (!DATA || !workerReady) return;
  updateLabels();
  postJob(getParams());
}

// ── Apply result ──────────────────────────────────────────────
function applyResult() {
  pendingRaf = null;
  const r = pendingResult;
  if (!r) return;
  pendingResult = null;

  const { yearRows, lifetimeSavings, lotInventory } = r;

  updateCallout(yearRows, lifetimeSavings);
  renderLotChart(lotInventory);
  renderTaxBarChart(yearRows);
  renderCumulativeChart(yearRows);
  renderSavingsChart(yearRows);
  renderHeadroomChart(yearRows);
  renderYearTable(yearRows);
  renderLotTable(lotInventory);

  hideIndicator();
}

// ── Callout ───────────────────────────────────────────────────
function updateCallout(rows, lifetimeSavings) {
  const totalLTCG = rows[rows.length - 1]?.cumulativeLTCG || 0;
  const totalFed = rows.reduce((s, r) => s + r.fedTaxStrategy, 0);
  const totalCA = rows.reduce((s, r) => s + r.caTaxStrategy, 0);
  const p = getParams();

  document.getElementById('callout-savings').textContent = fmt$(lifetimeSavings);
  document.getElementById('callout-savings').style.color = lifetimeSavings >= 0 ? '#3fb950' : '#f85149';
  document.getElementById('callout-years').textContent = p.years;
  document.getElementById('callout-ltcg').textContent = fmtK(totalLTCG);
  document.getElementById('callout-fed').textContent = fmtK(totalFed);
  document.getElementById('callout-ca').textContent = fmtK(totalCA);
}

// ── Shared chart config ───────────────────────────────────────
const tooltipStyle = {
  backgroundColor: '#161b22',
  borderColor: '#79c0ff',
  borderWidth: 1,
  titleColor: '#c9d1d9',
  bodyColor: '#c9d1d9',
  padding: 10,
  cornerRadius: 6,
  titleFont: { family: "'JetBrains Mono', monospace", size: 11 },
  bodyFont: { family: "'JetBrains Mono', monospace", size: 11 },
};

function initCharts() {
  Chart.defaults.color = '#8b949e';
  Chart.defaults.font = { family: "'JetBrains Mono', monospace" };

  const commonScaleX = {
    grid: { color: '#30363d' },
    ticks: { font: { size: 10 } },
  };
  const commonScaleY = {
    grid: { color: '#30363d' },
    ticks: {
      callback: (v) => fmtK(v),
      font: { size: 10 },
    },
  };

  // 1. Lot inventory — horizontal bar
  charts.lots = new Chart(document.getElementById('chart-lots'), {
    type: 'bar',
    data: { labels: [], datasets: [] },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          ...tooltipStyle,
          callbacks: {
            title: (items) => items[0].label,
            label: (item) => {
              const d = item.dataset._lotMeta?.[item.dataIndex];
              if (!d) return '';
              return [
                'MV: ' + fmt$(d.mv),
                'Basis: ' + fmt$(d.totalCost),
                'Qty: ' + (d.qty != null ? d.qty.toFixed(3) : '—'),
                'Cost/sh: ' + (d.costPerShare ? fmt$(d.costPerShare) : '—'),
                'Basis/MV: ' + fmtPct(d.basisRatio * 100),
                'Gain: ' + fmtPct(d.gainPct),
                d.isShortTerm ? 'SHORT-TERM' : 'Long-term',
              ];
            },
          },
        },
      },
      scales: {
        x: { ...commonScaleX, title: { display: true, text: 'Basis/MV %', font: { size: 10 } } },
        y: { grid: { color: '#30363d' }, ticks: { font: { size: 9 }, maxTicksLimit: 30 } },
      },
      animation: { duration: 100 },
    },
  });

  // 2. Tax bar chart
  charts.taxBar = new Chart(document.getElementById('chart-tax-bar'), {
    type: 'bar',
    data: { labels: [], datasets: [] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: true, labels: { font: { size: 10 }, boxWidth: 12 } },
        tooltip: { ...tooltipStyle, callbacks: { label: (i) => i.dataset.label + ': ' + fmt$(i.raw) } },
      },
      scales: {
        x: commonScaleX,
        y: { ...commonScaleY, title: { display: true, text: 'Federal tax ($)', font: { size: 10 } } },
      },
      animation: { duration: 150 },
    },
  });

  // 3. Cumulative chart
  charts.cumulative = new Chart(document.getElementById('chart-cumulative'), {
    type: 'line',
    data: { labels: [], datasets: [] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      elements: { point: { radius: 3 } },
      plugins: {
        legend: { display: true, labels: { font: { size: 10 }, boxWidth: 12 } },
        tooltip: { ...tooltipStyle, callbacks: { label: (i) => i.dataset.label + ': ' + fmt$(i.raw) } },
      },
      scales: {
        x: commonScaleX,
        y: { ...commonScaleY },
      },
      animation: { duration: 150 },
    },
  });

  // 4. Savings chart
  charts.savings = new Chart(document.getElementById('chart-savings'), {
    type: 'bar',
    data: { labels: [], datasets: [] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { ...tooltipStyle, callbacks: { label: (i) => 'Savings: ' + fmt$(i.raw) } },
      },
      scales: {
        x: commonScaleX,
        y: { ...commonScaleY, title: { display: true, text: 'Tax savings ($)', font: { size: 10 } } },
      },
      animation: { duration: 150 },
    },
  });

  // 5. Headroom chart
  charts.headroom = new Chart(document.getElementById('chart-headroom'), {
    type: 'bar',
    data: { labels: [], datasets: [] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: true, labels: { font: { size: 10 }, boxWidth: 12 } },
        tooltip: { ...tooltipStyle, callbacks: { label: (i) => i.dataset.label + ': ' + fmt$(i.raw) } },
      },
      scales: {
        x: commonScaleX,
        y: { ...commonScaleY, stacked: false, title: { display: true, text: 'Dollars ($)', font: { size: 10 } } },
      },
      animation: { duration: 150 },
    },
  });
}

// ── Chart renders ─────────────────────────────────────────────

function renderLotChart(lots) {
  // Show all lots sorted by basisRatio desc — bar = basisRatio value
  // Color: green=low basis (big gain), yellow=mid, red=high basis
  const labels = lots.map((l) => `${l.symbol} ${l.acquired}`);
  const values = lots.map((l) => +(l.basisRatio * 100).toFixed(1));
  const colors = lots.map((l) => {
    if (l.isShortTerm) return '#f8514988'; // ST = red regardless
    const r = l.basisRatio;
    if (r < 0.4) return '#3fb95088'; // low basis = lots of gain = green (good to harvest LT)
    if (r < 0.7) return '#d2992288'; // medium
    return '#79c0ff88'; // high basis = less gain = blue (preferred to sell under HIFO)
  });

  const dataset = {
    data: values,
    backgroundColor: colors,
    borderColor: colors.map((c) => c.replace('88', 'cc')),
    borderWidth: 1,
    _lotMeta: lots,
  };

  charts.lots.data.labels = labels;
  charts.lots.data.datasets = [dataset];
  charts.lots.update();
}

function renderTaxBarChart(rows) {
  const labels = rows.map((r) => String(r.year));
  charts.taxBar.data.labels = labels;
  charts.taxBar.data.datasets = [
    {
      label: 'Fed (strategy)',
      data: rows.map((r) => r.fedTaxStrategy),
      backgroundColor: '#79c0ff88',
      borderColor: '#79c0ffcc',
      borderWidth: 1,
    },
    {
      label: 'Fed (baseline)',
      data: rows.map((r) => r.fedTaxBaseline),
      backgroundColor: '#30363d88',
      borderColor: '#30363dcc',
      borderWidth: 1,
    },
  ];
  charts.taxBar.update();
}

function renderCumulativeChart(rows) {
  const labels = rows.map((r) => String(r.year));
  charts.cumulative.data.labels = labels;
  charts.cumulative.data.datasets = [
    {
      label: 'Cum. LTCG harvested',
      data: rows.map((r) => r.cumulativeLTCG),
      borderColor: '#79c0ff',
      backgroundColor: '#79c0ff22',
      fill: false,
      tension: 0.2,
      borderWidth: 2,
    },
    {
      label: 'Cum. tax (strategy)',
      data: rows.map((r) => r.cumulativeTaxStrategy),
      borderColor: '#3fb950',
      backgroundColor: '#3fb95022',
      fill: false,
      tension: 0.2,
      borderWidth: 2,
    },
    {
      label: 'Cum. tax (baseline)',
      data: rows.map((r) => r.cumulativeTaxBaseline),
      borderColor: '#30363d',
      backgroundColor: 'transparent',
      fill: false,
      tension: 0.2,
      borderWidth: 1.5,
      borderDash: [4, 3],
    },
  ];
  charts.cumulative.update();
}

function renderSavingsChart(rows) {
  const labels = rows.map((r) => String(r.year));
  const values = rows.map((r) => r.taxSavingsVsBaseline);
  const colors = values.map((v) => v >= 0 ? '#3fb95088' : '#f8514988');
  charts.savings.data.labels = labels;
  charts.savings.data.datasets = [{
    data: values,
    backgroundColor: colors,
    borderColor: colors.map((c) => c.replace('88', 'cc')),
    borderWidth: 1,
  }];
  charts.savings.update();
}

function renderHeadroomChart(rows) {
  const labels = rows.map((r) => String(r.year));
  charts.headroom.data.labels = labels;
  charts.headroom.data.datasets = [
    {
      label: '0%-LTCG headroom',
      data: rows.map((r) => r.ltcg0Headroom),
      backgroundColor: '#1f6feb55',
      borderColor: '#79c0ff88',
      borderWidth: 1,
    },
    {
      label: 'LTCG realized',
      data: rows.map((r) => r.ltcgRealized),
      backgroundColor: '#3fb95055',
      borderColor: '#3fb95088',
      borderWidth: 1,
    },
  ];
  charts.headroom.update();
}

// ── Year table ────────────────────────────────────────────────
function renderYearTable(rows) {
  const tbody = document.getElementById('year-tbody');
  tbody.innerHTML = '';
  rows.forEach((r) => {
    const tr = document.createElement('tr');
    const savingsPosNeg = r.taxSavingsVsBaseline >= 0 ? 'green' : 'red';
    const cumSavingsPosNeg = r.cumulativeSavings >= 0 ? 'green' : 'red';
    tr.innerHTML = [
      `<td>${r.year}</td>`,
      `<td>${fmt$(r.ordinaryIncome)}</td>`,
      `<td>${fmt$(Math.max(0, r.ordinaryIncome - (DATA?.taxBrackets?.stdDeduction || 15000)))}</td>`,
      `<td>${fmt$(r.ltcgRealized)}</td>`,
      `<td class="${r.ltcgRealized <= r.ltcg0Headroom ? 'green' : 'red'}">${fmt$(r.ltcg0Headroom)}</td>`,
      `<td class="${r.fedTaxStrategy === 0 ? 'green' : ''}">${fmt$(r.fedTaxStrategy)}</td>`,
      `<td class="muted">${fmt$(r.fedTaxBaseline)}</td>`,
      `<td>${fmt$(r.caTaxStrategy)}</td>`,
      `<td class="muted">${fmt$(r.caTaxBaseline)}</td>`,
      `<td class="${savingsPosNeg}">${fmt$(r.taxSavingsVsBaseline)}</td>`,
      `<td class="${cumSavingsPosNeg}">${fmt$(r.cumulativeSavings)}</td>`,
    ].join('');
    tbody.appendChild(tr);
  });
}

// ── Lot table ─────────────────────────────────────────────────
function renderLotTable(lots) {
  const tbody = document.getElementById('lot-tbody');
  tbody.innerHTML = '';
  lots.forEach((l) => {
    const tr = document.createElement('tr');
    const typeClass = l.isShortTerm ? 'lot-st' : 'lot-lt';
    const gainPct = l.mv > 0 ? ((l.mv - l.totalCost) / l.totalCost * 100) : 0;
    const unrealizedGain = l.mv - l.totalCost;
    tr.innerHTML = [
      `<td>${l.symbol}</td>`,
      `<td>${l.acquired}</td>`,
      `<td class="${typeClass}">${l.isShortTerm ? 'ST' : 'LT'}</td>`,
      `<td>${l.qty != null ? l.qty.toFixed(3) : '—'}</td>`,
      `<td>${l.costPerShare ? fmt$(l.costPerShare) : '—'}</td>`,
      `<td>${fmt$(l.totalCost)}</td>`,
      `<td>${fmt$(l.mv)}</td>`,
      `<td class="${unrealizedGain >= 0 ? 'green' : 'red'}">${fmt$(unrealizedGain)}</td>`,
      `<td>${fmtPct(l.basisRatio * 100)}</td>`,
      `<td class="${gainPct >= 0 ? 'green' : 'red'}">${fmtPct(gainPct)}</td>`,
    ].join('');
    tbody.appendChild(tr);
  });
}
