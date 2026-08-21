/* ──────────────────────────────────────────────────────────
   Grad-School Portfolio MC Dashboard — app.js
   Data: Damodaran 1928-2024 real US equity returns (97 years)
   Bootstrap only — no synthetic/parametric distribution
   MC runs in mc_worker.js (Web Worker) — no main-thread blocking
   ────────────────────────────────────────────────────────── */

const START_YEAR = 2026;

// ── Helpers ────────────────────────────────────────────────
const fmt$ = (v) =>
  (v < 0 ? '-$' : '$') +
  Math.abs(Math.round(v)).toLocaleString('en-US');

const fmtPct = (v) => (v * 100).toFixed(1) + '%';

const pctColor = (p, direction = 'bad') => {
  if (direction === 'bad') return p > 0.15 ? '#f85149' : p > 0.05 ? '#d29922' : '#3fb950';
  return p > 0.6 ? '#3fb950' : p > 0.35 ? '#d29922' : '#f85149';
};

// ── State ───────────────────────────────────────────────────
let DATA = null;
let charts = {};
let worker = null;
let workerReady = false;
let jobCounter = 0;
let latestJobId = -1;
let pendingRaf = null;
let pendingResult = null;
let computingIndicatorTimer = null;

// ── Worker setup ────────────────────────────────────────────
function initWorker() {
  worker = new Worker('mc_worker.js');
  worker.onmessage = function (e) {
    const msg = e.data;
    if (msg.type === 'ready') {
      workerReady = true;
      runAndRender();
      return;
    }
    if (msg.type === 'result') {
      // Ignore stale results from superseded jobs
      if (msg.jobId !== latestJobId) return;
      pendingResult = msg;
      // Batch chart updates via rAF so rapid results don't thrash canvas
      if (pendingRaf) cancelAnimationFrame(pendingRaf);
      pendingRaf = requestAnimationFrame(applyResult);
    }
  };
  worker.onerror = function (err) {
    console.error('mc_worker error:', err);
    hideComputingIndicator();
  };
}

function postJob(params) {
  if (!workerReady) return;
  const jobId = ++jobCounter;
  latestJobId = jobId;
  showComputingIndicator();
  worker.postMessage({ type: 'run', jobId, params });
}

// ── Load data ───────────────────────────────────────────────
fetch('data.json')
  .then((r) => r.json())
  .then((d) => {
    DATA = d;
    console.log(
      'Loaded Damodaran series: years=%d, mean_real=%.3f, stdev_real=%.3f',
      d.stats.count,
      d.stats.mean_real,
      d.stats.stdev_real
    );
    initCharts();
    bindControls();
    initWorker();
    // Worker posts 'ready' → triggers first runAndRender
    // Send data to worker on init
    worker.postMessage({ type: 'init', returns: d.realReturns, years: d.years });
  })
  .catch((e) => {
    console.error('Failed to load data.json', e);
    document.body.innerHTML +=
      '<p style="color:#f85149;padding:24px">Error loading data.json: ' + e + '</p>';
  });

// ── Computing indicator ──────────────────────────────────────
function showComputingIndicator() {
  clearTimeout(computingIndicatorTimer);
  // Only show after 80ms so fast results don't flash the indicator
  computingIndicatorTimer = setTimeout(() => {
    const el = document.getElementById('loading-indicator');
    if (el) el.style.display = 'flex';
  }, 80);
}

function hideComputingIndicator() {
  clearTimeout(computingIndicatorTimer);
  const el = document.getElementById('loading-indicator');
  if (el) el.style.display = 'none';
}

// ── Bind controls ────────────────────────────────────────────
function bindControls() {
  const sliders = ['sl-start', 'sl-spend', 'sl-masters', 'sl-phd', 'sl-stipend', 'sl-nsims'];
  sliders.forEach((id) => {
    const el = document.getElementById(id);
    // oninput: ONLY update display labels + enqueue job. No compute.
    el.addEventListener('input', () => {
      updateLabels();
      scheduleSim();
    });
  });

  document.querySelectorAll('input[name="mode"]').forEach((r) =>
    r.addEventListener('change', () => {
      const isBlock = document.querySelector('input[name="mode"]:checked').value === 'block';
      document.getElementById('block-size-row').style.display = isBlock ? 'flex' : 'none';
      scheduleSim();
    })
  );
  document.querySelectorAll('input[name="blocksize"]').forEach((r) =>
    r.addEventListener('change', scheduleSim)
  );
}

let debounceTimer = null;
function scheduleSim() {
  if (debounceTimer) clearTimeout(debounceTimer);
  // Short debounce — cancel-in-flight handles the rest
  debounceTimer = setTimeout(runAndRender, 30);
}

// ── Read params ──────────────────────────────────────────────
function getParams() {
  return {
    start: +document.getElementById('sl-start').value,
    spend: +document.getElementById('sl-spend').value,
    masters: +document.getElementById('sl-masters').value,
    phd: +document.getElementById('sl-phd').value,
    stipend: +document.getElementById('sl-stipend').value,
    nSims: +document.getElementById('sl-nsims').value,
    mode: document.querySelector('input[name="mode"]:checked').value,
    blockSize: +document.querySelector('input[name="blocksize"]:checked').value,
  };
}

function updateLabels() {
  const start = +document.getElementById('sl-start').value;
  const spend = +document.getElementById('sl-spend').value;
  const masters = +document.getElementById('sl-masters').value;
  const phd = +document.getElementById('sl-phd').value;
  const stipend = +document.getElementById('sl-stipend').value;
  const nSims = +document.getElementById('sl-nsims').value;

  document.getElementById('lbl-start').textContent = fmt$(start);
  document.getElementById('lbl-spend').textContent = fmt$(spend);
  document.getElementById('lbl-masters').textContent = masters;
  document.getElementById('lbl-phd').textContent = phd;
  document.getElementById('lbl-stipend').textContent = fmt$(stipend);
  document.getElementById('lbl-nsims').textContent = nSims.toLocaleString('en-US');

  // Show slow-run hint when > 20k sims
  const hintEl = document.getElementById('nsims-hint');
  if (hintEl) {
    if (nSims > 20000) {
      const secs = Math.max(1, Math.ceil(nSims / 50000));
      hintEl.textContent = 'may take ~' + secs + 's';
    } else {
      hintEl.textContent = '';
    }
  }

  const horizon = masters + phd;
  document.getElementById('d-horizon').textContent = horizon + ' year' + (horizon !== 1 ? 's' : '');
  document.getElementById('d-endyr').textContent = START_YEAR + horizon;

  const mastersNet = -spend;
  const phdNet = stipend - spend;
  const totalDrain = masters * spend + phd * (spend - stipend);

  document.getElementById('d-drain').textContent =
    'Masters: ' + fmt$(mastersNet) + '/yr  |  PhD: ' + fmt$(phdNet) + '/yr';
  document.getElementById('d-total-drain').textContent = fmt$(-totalDrain) + ' (real 2026 USD)';
}

// ── Main run (enqueue job to worker) ─────────────────────────
function runAndRender() {
  if (!DATA || !workerReady) return;
  updateLabels();
  postJob(getParams());
}

// ── Apply result (called in rAF after worker responds) ────────
function applyResult() {
  pendingRaf = null;
  const r = pendingResult;
  if (!r) return;
  pendingResult = null;

  const p = getParams();
  const { binCounts, binMin, BIN: binWidth,
          samplePaths, percentilePaths,
          pct5, pct25, pct50, pct75, pct95,
          probabilities, decadeReplay, horizon } = r;

  const yearLabels = Array.from({ length: horizon + 1 }, (_, i) => START_YEAR + i);

  renderHistogram(binCounts, binMin, binWidth, p.start, pct5, pct25, pct50, pct75, pct95, horizon);
  renderSamplePaths(samplePaths, yearLabels, p.start, pct50, horizon);
  renderDecadeReplay(decadeReplay, horizon);
  renderPercentilePaths(percentilePaths, yearLabels, horizon, p.start);

  // Probability table
  setProb('p-lt-start', probabilities.ltStart, 'bad');
  setProb('p-lt-1m', probabilities.lt1M, 'bad');
  setProb('p-lt-500k', probabilities.lt500K, 'bad');
  setProb('p-ruin', probabilities.ruin, 'bad');
  setProb('p-gt-start', probabilities.gtStart, 'good');
  setProb('p-gt-2x', probabilities.gt2x, 'good');

  const isGood = pct50 >= p.start;
  document.getElementById('hist-subtitle').textContent =
    '— median ' + fmt$(pct50) + ' · 5th ' + fmt$(pct5) + ' · 95th ' + fmt$(pct95);
  document.getElementById('hist-subtitle').style.color = isGood ? '#3fb950' : '#f85149';

  hideComputingIndicator();
}

function setProb(id, val, direction) {
  const el = document.getElementById(id);
  el.textContent = fmtPct(val);
  el.className = 'value ' + (direction === 'bad' ? pctColor(val, 'bad') === '#3fb950' ? 'good' : pctColor(val, 'bad') === '#d29922' ? 'warn' : 'bad' : pctColor(val, 'good') === '#3fb950' ? 'good' : pctColor(val, 'good') === '#d29922' ? 'warn' : 'bad');
}

// ── Shared tooltip style ─────────────────────────────────────
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

// ── Chart initialization ─────────────────────────────────────
function initCharts() {
  const commonFont = { family: "'JetBrains Mono', monospace" };

  Chart.defaults.color = '#8b949e';
  Chart.defaults.font = commonFont;

  // 1. Histogram
  charts.hist = new Chart(document.getElementById('chart-hist'), {
    type: 'bar',
    data: { labels: [], datasets: [] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'nearest', intersect: true },
      plugins: {
        legend: { display: false },
        tooltip: {
          ...tooltipStyle,
          callbacks: {
            title: (items) => {
              // items[0].label is the bin-start dollar string
              const item = items[0];
              const chart = item.chart;
              const binW = chart._binWidth || 250000;
              const lo = item.label;
              const loVal = item.parsed.x;
              // compute bin edges from stored data
              const binMin = chart._binMin || 0;
              const binIdx = item.dataIndex;
              const binLoVal = binMin + binIdx * binW;
              const binHiVal = binLoVal + binW;
              const loK = Math.round(binLoVal / 1000);
              const hiK = Math.round(binHiVal / 1000);
              return '$' + loK.toLocaleString('en-US') + 'k – $' + hiK.toLocaleString('en-US') + 'k (real 2026 USD)';
            },
            label: (item) => {
              const chart = item.chart;
              const count = item.raw;
              const total = chart._binTotal || 1;
              const pct = ((count / total) * 100).toFixed(1);
              return count.toLocaleString('en-US') + ' simulations (' + pct + '%)';
            },
          },
        },
      },
      scales: {
        x: {
          grid: { color: '#30363d' },
          ticks: { maxRotation: 45, font: { size: 10 } },
          title: { display: true, text: 'Ending balance (real 2026 USD)', font: { size: 10 } },
        },
        y: {
          grid: { color: '#30363d' },
          title: { display: true, text: '# simulations', font: { size: 11 } },
        },
      },
      animation: { duration: 150 },
    },
  });

  // 2. Sample paths
  // We store medIdx on the chart so onHover/mouseleave can reference it
  charts.paths = new Chart(document.getElementById('chart-paths'), {
    type: 'line',
    data: { labels: [], datasets: [] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      elements: { point: { radius: 0 } },
      interaction: { mode: 'nearest', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          ...tooltipStyle,
          callbacks: {
            title: (items) => {
              const item = items[0];
              return 'Year ' + item.label;
            },
            label: (item) => {
              // Skip the Start reference line (last dataset)
              const chart = item.chart;
              const dsIdx = item.datasetIndex;
              const nDatasets = chart.data.datasets.length;
              if (dsIdx === nDatasets - 1) return null; // Start ref line
              const runId = dsIdx;
              return 'Balance ' + fmt$(item.raw) + ' real 2026 USD  [path #' + runId + ']';
            },
            filter: (item) => {
              // Suppress the Start reference line entry
              const chart = item.chart;
              const nDatasets = chart.data.datasets.length;
              return item.datasetIndex !== nDatasets - 1;
            },
          },
        },
      },
      onHover: (event, elements, chart) => {
        if (!chart.data.datasets.length) return;
        const nDs = chart.data.datasets.length;
        const startDsIdx = nDs - 1; // always the last = Start ref
        const medIdx = chart._medIdx != null ? chart._medIdx : -1;

        if (elements.length === 0) {
          // mouseleave — reset all to defaults
          chart.data.datasets.forEach((ds, i) => {
            if (i === startDsIdx) return; // skip Start line
            if (i === medIdx) {
              ds.borderColor = '#79c0ff';
              ds.borderWidth = 3;
            } else {
              ds.borderColor = '#79c0ff18';
              ds.borderWidth = 1;
            }
          });
          chart.update('none');
          return;
        }

        const hoveredIdx = elements[0].datasetIndex;
        chart.data.datasets.forEach((ds, i) => {
          if (i === startDsIdx) return; // skip Start line
          if (i === hoveredIdx) {
            ds.borderColor = '#79c0ff';
            ds.borderWidth = 3;
          } else {
            ds.borderColor = '#79c0ff18';
            ds.borderWidth = 0.5;
          }
        });
        chart.update('none');
      },
      scales: {
        x: {
          grid: { color: '#30363d' },
          title: { display: true, text: 'Year', font: { size: 10 } },
        },
        y: {
          grid: { color: '#30363d' },
          title: { display: true, text: 'Balance (real 2026 USD)', font: { size: 10 } },
          ticks: {
            callback: (v) => '$' + (v / 1e6).toFixed(1) + 'M',
            font: { size: 10 },
          },
        },
      },
      animation: { duration: 150 },
    },
  });

  // 3. Decade replay
  charts.replay = new Chart(document.getElementById('chart-replay'), {
    type: 'bar',
    data: { labels: [], datasets: [] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'nearest', intersect: true },
      plugins: {
        legend: { display: false },
        tooltip: {
          ...tooltipStyle,
          callbacks: {
            title: (items) => {
              const item = items[0];
              const chart = item.chart;
              const meta = chart._decadeMeta;
              if (!meta) return String(item.label);
              const row = meta[item.dataIndex];
              if (!row) return String(item.label);
              return row.startYear + '\u2013' + row.endYear;
            },
            label: (item) => {
              const chart = item.chart;
              const meta = chart._decadeMeta;
              const row = meta ? meta[item.dataIndex] : null;
              const ending = fmt$(item.raw);
              if (!row) return 'Ending: ' + ending;
              const dd = (row.maxDrawdown * 100).toFixed(1);
              return ['Ending: ' + ending, 'Max drawdown: ' + dd + '%'];
            },
          },
        },
      },
      scales: {
        x: {
          grid: { color: '#30363d' },
          ticks: { font: { size: 10 } },
          title: { display: true, text: 'Starting year of historical window', font: { size: 10 } },
        },
        y: {
          grid: { color: '#30363d' },
          title: { display: true, text: 'Ending balance (real 2026 USD)', font: { size: 10 } },
          ticks: {
            callback: (v) => '$' + (v / 1e6).toFixed(1) + 'M',
            font: { size: 10 },
          },
        },
      },
      animation: { duration: 150 },
    },
  });

  // 4. Percentile paths
  charts.pctl = new Chart(document.getElementById('chart-pctl'), {
    type: 'line',
    data: { labels: [], datasets: [] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      elements: { point: { radius: 0 } },
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: {
          display: true,
          labels: { font: { size: 10 }, boxWidth: 12 },
        },
        tooltip: {
          ...tooltipStyle,
          callbacks: {
            title: (items) => 'Year ' + items[0].label,
            label: (item) => {
              const label = item.dataset.label || '';
              // Skip the fill band and start-line datasets
              if (!label || label === '5-95 band' || label.startsWith('Start:')) return null;
              return label + ': ' + fmt$(item.raw) + ' real 2026 USD';
            },
            filter: (item) => {
              const label = item.dataset.label || '';
              return label && label !== '5-95 band' && !label.startsWith('Start:');
            },
          },
        },
      },
      scales: {
        x: {
          grid: { color: '#30363d' },
          title: { display: true, text: 'Year', font: { size: 10 } },
        },
        y: {
          grid: { color: '#30363d' },
          title: { display: true, text: 'Balance (real 2026 USD)', font: { size: 10 } },
          ticks: {
            callback: (v) => '$' + (v / 1e6).toFixed(1) + 'M',
            font: { size: 10 },
          },
        },
      },
      animation: { duration: 150 },
    },
  });
}

// ── Histogram ────────────────────────────────────────────────
function renderHistogram(binCounts, binMin, binWidth, start, pct5, pct25, pct50, pct75, pct95, horizon) {
  const nBins = binCounts.length;
  const bins = Array.from({ length: nBins }, (_, i) => binMin + i * binWidth);

  const isGood = pct50 >= start;
  const barColor = bins.map((b) => {
    const mid = b + binWidth / 2;
    if (mid < pct5) return '#f8514988';
    if (mid < pct25) return '#d2992288';
    if (mid < pct75) return isGood ? '#3fb95088' : '#79c0ff88';
    if (mid < pct95) return '#d2992288';
    return '#3fb95088';
  });

  const labels = bins.map((b) => fmt$(b));

  // Annotation lines
  const lines = [
    { label: 'Start', val: start, color: '#79c0ff', yOff: 10 },
    { label: 'p5', val: pct5, color: '#f85149', yOff: 10 },
    { label: 'p25', val: pct25, color: '#d29922', yOff: 50 },
    { label: 'p50', val: pct50, color: isGood ? '#3fb950' : '#f85149', yOff: 90 },
    { label: 'p75', val: pct75, color: '#d29922', yOff: 130 },
    { label: 'p95', val: pct95, color: '#3fb950', yOff: 10 },
  ];

  // Store metadata for tooltip callbacks
  charts.hist._binWidth = binWidth;
  charts.hist._binMin = binMin;
  charts.hist._binTotal = binCounts.reduce((a, b) => a + b, 0);

  charts.hist.data.labels = labels;
  charts.hist.data.datasets = [
    {
      data: binCounts,
      backgroundColor: barColor,
      borderColor: barColor.map((c) => c.replace('88', 'ff')),
      borderWidth: 1,
      barPercentage: 1.0,
      categoryPercentage: 1.0,
    },
  ];

  charts.hist.update();

  // Store annotation data for afterDraw custom plugin
  charts.hist._annotLines = lines.map((l) => ({
    binIdx: (l.val - binMin) / binWidth,
    color: l.color,
    label: l.label,
    yOff: l.yOff,
  }));

  if (!charts.hist._annotPluginSet) {
    charts.hist._annotPluginSet = true;
    const annotPlugin = {
      id: 'histAnnot',
      afterDraw(chart) {
        if (!chart._annotLines) return;
        const { ctx, scales, chartArea } = chart;
        const xScale = scales.x;
        if (!xScale) return;
        ctx.save();
        for (const line of chart._annotLines) {
          const px = xScale.getPixelForValue(line.binIdx - 0.5);
          if (px < chartArea.left || px > chartArea.right) continue;
          ctx.beginPath();
          ctx.strokeStyle = line.color;
          ctx.lineWidth = 1.5;
          ctx.setLineDash([4, 3]);
          ctx.moveTo(px, chartArea.top);
          ctx.lineTo(px, chartArea.bottom);
          ctx.stroke();
          ctx.setLineDash([]);
          ctx.fillStyle = line.color;
          ctx.font = '9px monospace';
          ctx.save();
          ctx.translate(px + 3, chartArea.top + line.yOff);
          ctx.fillText(line.label, 0, 0);
          ctx.restore();
        }
        ctx.restore();
      },
    };
    Chart.register(annotPlugin);
  }

  charts.hist.update();
}

// ── Sample paths ─────────────────────────────────────────────
function renderSamplePaths(samplePaths, yearLabels, start, medianEnd, horizon) {
  const datasets = samplePaths.map((path) => ({
    data: path,
    borderColor: '#79c0ff18',
    borderWidth: 1,
    fill: false,
    tension: 0,
    pointRadius: 0,
    label: '',
  }));

  // Highlight the path closest to median at final year
  const dists = samplePaths.map((p, i) => ({
    i,
    d: Math.abs(p[p.length - 1] - medianEnd),
  }));
  dists.sort((a, b) => a.d - b.d);
  const medIdx = dists[0].i;
  datasets[medIdx].borderColor = '#79c0ff';
  datasets[medIdx].borderWidth = 3;
  datasets[medIdx].label = 'Median path';

  // Store medIdx on chart so onHover can reference it
  charts.paths._medIdx = medIdx;

  // Start line
  datasets.push({
    data: Array(yearLabels.length).fill(start),
    borderColor: '#30363d',
    borderWidth: 1,
    borderDash: [4, 3],
    fill: false,
    pointRadius: 0,
    label: 'Start: ' + fmt$(start),
  });

  charts.paths.data.labels = yearLabels;
  charts.paths.data.datasets = datasets;
  charts.paths.update();

  document.getElementById('paths-subtitle').textContent =
    '— 50 random draws, bold = closest to median';
}

// ── Percentile paths ─────────────────────────────────────────
function renderPercentilePaths(percentilePaths, yearLabels, horizon, start) {
  const pctiles = ['pct5', 'pct25', 'pct50', 'pct75', 'pct95'];
  const pctLabels = ['5th', '25th', '50th', '75th', '95th'];
  const pctColors = ['#f85149', '#d29922', '#79c0ff', '#d29922', '#3fb950'];
  const pctWidths = [1.5, 1.5, 2.5, 1.5, 1.5];
  const pctDash = [[4, 3], [2, 2], [], [2, 2], [4, 3]];

  const datasets = pctiles.map((key, pi) => ({
    label: pctLabels[pi] + ' pctl',
    data: percentilePaths[key],
    borderColor: pctColors[pi],
    borderWidth: pctWidths[pi],
    borderDash: pctDash[pi],
    fill: false,
    tension: 0.1,
    pointRadius: 0,
  }));

  // Shaded band 5-95
  datasets.push({
    label: '5-95 band',
    data: percentilePaths.pct95,
    fill: '-5',
    backgroundColor: '#79c0ff08',
    borderColor: 'transparent',
    pointRadius: 0,
    tension: 0.1,
  });

  // Start reference line
  datasets.push({
    label: 'Start: ' + fmt$(start),
    data: Array(yearLabels.length).fill(start),
    borderColor: '#30363d',
    borderWidth: 1,
    borderDash: [4, 3],
    fill: false,
    pointRadius: 0,
    tension: 0,
  });

  charts.pctl.data.labels = yearLabels;
  charts.pctl.data.datasets = datasets;
  charts.pctl.update();

  document.getElementById('pctl-subtitle').textContent =
    '— p5/p25/p50/p75/p95 bands';
}

// ── Decade replay ─────────────────────────────────────────────
function renderDecadeReplay(results, horizon) {
  if (!results || results.length === 0) {
    charts.replay.data.labels = [];
    charts.replay.data.datasets = [];
    charts.replay.update();
    return;
  }

  const minEnd = Math.min(...results.map((r) => r.ending));
  const maxEnd = Math.max(...results.map((r) => r.ending));

  const worstIdx = results.findIndex((r) => r.ending === minEnd);
  const bestIdx = results.findIndex((r) => r.ending === maxEnd);

  const labels = results.map((r) => r.startYear);
  const data = results.map((r) => r.ending);

  const barColors = results.map((r, i) => {
    if (i === worstIdx) return '#f85149';
    if (i === bestIdx) return '#3fb950';
    const ratio = (r.ending - minEnd) / (maxEnd - minEnd);
    const g = Math.round(80 + ratio * 120);
    const b = Math.round(80 + (1 - ratio) * 120);
    return `rgba(80,${g},${b},0.75)`;
  });

  // Store decade metadata for tooltip callbacks
  charts.replay._decadeMeta = results;

  charts.replay.data.labels = labels;
  charts.replay.data.datasets = [
    {
      data,
      backgroundColor: barColors,
      borderColor: barColors.map((c) => c),
      borderWidth: 1,
    },
  ];
  charts.replay.update();

  document.getElementById('replay-subtitle').textContent =
    '— window: ' + horizon + 'yr · worst start: ' +
    results[worstIdx].startYear + ' (' + fmt$(minEnd) + ') · best: ' +
    results[bestIdx].startYear + ' (' + fmt$(maxEnd) + ')';
}
