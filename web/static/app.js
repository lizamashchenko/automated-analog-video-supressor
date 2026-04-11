/* ------------------------------------------------------------------ */
/* State                                                                */
/* ------------------------------------------------------------------ */
const state = {
    running: false,
    sweepNum: 0,
    minFreq: 100,    // MHz (from config, overridden on sweep_start)
    maxFreq: 6000,
    currentFreq: null,
    // per-sweep spectrum: freq_step_mhz -> avg_power (max of 256 bins)
    sweepPower: {},
};

/* ------------------------------------------------------------------ */
/* Spectrum canvas                                                      */
/* ------------------------------------------------------------------ */
const sweepCanvas  = document.getElementById('canvas-sweep');
const sweepCtx     = sweepCanvas.getContext('2d');
const windowCanvas = document.getElementById('canvas-window');
const windowCtx    = windowCanvas.getContext('2d');

// colour ramp: black → deep blue → cyan → green → yellow → red
const RAMP = (() => {
    const c = document.createElement('canvas');
    c.width = 256; c.height = 1;
    const g = c.getContext('2d').createLinearGradient(0, 0, 256, 0);
    g.addColorStop(0,    '#000000');
    g.addColorStop(0.15, '#0a0a3a');
    g.addColorStop(0.35, '#0066cc');
    g.addColorStop(0.55, '#00ccaa');
    g.addColorStop(0.72, '#33dd00');
    g.addColorStop(0.85, '#ffcc00');
    g.addColorStop(1.0,  '#ff2200');
    c.getContext('2d').fillStyle = g;
    c.getContext('2d').fillRect(0, 0, 256, 1);
    return c.getContext('2d').getImageData(0, 0, 256, 1).data;
})();

function powerToRGB(t) {
    const i = Math.min(255, Math.max(0, Math.round(t * 255))) * 4;
    return `rgb(${RAMP[i]},${RAMP[i+1]},${RAMP[i+2]})`;
}

function resizeCanvases() {
    const w = sweepCanvas.parentElement.clientWidth;
    if (sweepCanvas.width !== w) {
        sweepCanvas.width  = w;
        windowCanvas.width = w;
    }
}

// Track global min/max across current sweep for normalisation
let _sweepMin = Infinity, _sweepMax = -Infinity;

function resetSweepCanvas() {
    _sweepMin = Infinity; _sweepMax = -Infinity;
    state.sweepPower = {};
    resizeCanvases();
    sweepCtx.clearRect(0, 0, sweepCanvas.width, sweepCanvas.height);
    // draw dim grid
    sweepCtx.fillStyle = '#0a0a12';
    sweepCtx.fillRect(0, 0, sweepCanvas.width, sweepCanvas.height);
}

function paintSweepColumn(freqMHz, powerArr) {
    const W = sweepCanvas.width;
    const H = sweepCanvas.height;
    const span = state.maxFreq - state.minFreq;
    const x = Math.round(((freqMHz - state.minFreq) / span) * W);
    const colW = Math.max(1, Math.round((20 / span) * W)); // 20 MHz step

    // update global scale
    const avg = powerArr.reduce((s, v) => s + v, 0) / powerArr.length;
    const peak = Math.max(...powerArr);
    _sweepMin = Math.min(_sweepMin, avg - 5);
    _sweepMax = Math.max(_sweepMax, peak);

    state.sweepPower[Math.round(freqMHz)] = peak;

    // redraw this column using current scale
    const t = (_sweepMax - _sweepMin) < 1 ? 0.5
        : (peak - _sweepMin) / (_sweepMax - _sweepMin);
    sweepCtx.fillStyle = powerToRGB(Math.min(1, Math.max(0, t)));
    sweepCtx.fillRect(x, 0, colW, H);
}

function markPlateauOnSweep(freqMHz) {
    const W = sweepCanvas.width;
    const span = state.maxFreq - state.minFreq;
    const x = Math.round(((freqMHz - state.minFreq) / span) * W);
    sweepCtx.strokeStyle = '#f0883e';
    sweepCtx.lineWidth = 1;
    sweepCtx.beginPath();
    sweepCtx.moveTo(x, 0);
    sweepCtx.lineTo(x, sweepCanvas.height);
    sweepCtx.stroke();
}

function markVideoOnSweep(freqMHz, confirmed) {
    const W = sweepCanvas.width;
    const span = state.maxFreq - state.minFreq;
    const x = Math.round(((freqMHz - state.minFreq) / span) * W);
    sweepCtx.fillStyle = confirmed ? '#3fb950' : '#f85149';
    sweepCtx.fillRect(x - 1, 0, 3, sweepCanvas.height);
}

function paintWindowSpectrum(freqMHz, powerArr) {
    const W = windowCanvas.width;
    const H = windowCanvas.height;
    const n = powerArr.length;

    windowCtx.clearRect(0, 0, W, H);
    windowCtx.fillStyle = '#0a0a12';
    windowCtx.fillRect(0, 0, W, H);

    const min = Math.min(...powerArr);
    const max = Math.max(...powerArr);
    const range = max - min || 1;

    // spectrum line
    windowCtx.beginPath();
    windowCtx.strokeStyle = '#58a6ff';
    windowCtx.lineWidth = 1;
    for (let i = 0; i < n; i++) {
        const x = (i / n) * W;
        const y = H - ((powerArr[i] - min) / range) * (H - 4) - 2;
        i === 0 ? windowCtx.moveTo(x, y) : windowCtx.lineTo(x, y);
    }
    windowCtx.stroke();

    // fill under line
    windowCtx.lineTo(W, H); windowCtx.lineTo(0, H); windowCtx.closePath();
    windowCtx.fillStyle = 'rgba(88,166,255,0.08)';
    windowCtx.fill();

    // harmonic markers (15625 Hz, 31250 Hz, 46875 Hz, 62500 Hz within 20 MHz window)
    const sampleRate = 20e6;
    const harmonics = [15625, 31250, 46875, 62500];
    const colors = ['#f85149', '#f0883e', '#3fb950', '#58a6ff'];
    harmonics.forEach((f, i) => {
        // position relative to centre of window (FM demod spectrum is centred at 0)
        // but our spectrum here is IQ power — just mark as fraction of 20 MHz
        const frac = f / sampleRate;
        const xPos = (0.5 + frac) * W;  // positive side
        windowCtx.strokeStyle = colors[i];
        windowCtx.setLineDash([3, 3]);
        windowCtx.lineWidth = 1;
        windowCtx.beginPath();
        windowCtx.moveTo(xPos, 0);
        windowCtx.lineTo(xPos, H);
        windowCtx.stroke();
        windowCtx.setLineDash([]);
    });

    // frequency label
    windowCtx.fillStyle = '#6e7681';
    windowCtx.font = '10px monospace';
    windowCtx.fillText(`${(freqMHz - 10).toFixed(0)}`, 4, H - 4);
    windowCtx.fillText(`${freqMHz.toFixed(1)} MHz`, W / 2 - 24, 12);
    windowCtx.fillText(`${(freqMHz + 10).toFixed(0)}`, W - 36, H - 4);
}

/* ------------------------------------------------------------------ */
/* Tables                                                               */
/* ------------------------------------------------------------------ */
const plateauTbody   = document.getElementById('plateau-tbody');
const detectionTbody = document.getElementById('detection-tbody');
const MAX_TABLE_ROWS = 200;

function addRow(tbody, cells, cssClass) {
    const tr = document.createElement('tr');
    tr.className = (cssClass || '') + ' new-row';
    cells.forEach(c => {
        const td = document.createElement('td');
        td.textContent = c;
        tr.appendChild(td);
    });
    tbody.insertBefore(tr, tbody.firstChild);
    setTimeout(() => tr.classList.remove('new-row'), 700);
    while (tbody.rows.length > MAX_TABLE_ROWS)
        tbody.deleteRow(tbody.rows.length - 1);
}

/* ------------------------------------------------------------------ */
/* Event log                                                            */
/* ------------------------------------------------------------------ */
const eventLog = document.getElementById('event-log');
const MAX_LOG  = 300;

function logLine(text, cls) {
    const div = document.createElement('div');
    div.className = 'log-line ' + (cls || 'info');
    const ts = new Date().toTimeString().slice(0, 8);
    div.innerHTML = `<span class="ts">${ts}</span>${text}`;
    eventLog.insertBefore(div, eventLog.firstChild);
    while (eventLog.children.length > MAX_LOG)
        eventLog.removeChild(eventLog.lastChild);
}

/* ------------------------------------------------------------------ */
/* SSE handlers                                                         */
/* ------------------------------------------------------------------ */
function handleStatus(d) {
    state.running = d.state === 'running';
    const dot   = document.getElementById('status-dot');
    const label = document.getElementById('status-label');
    const info  = document.getElementById('run-info');

    dot.className = d.state === 'running' ? 'running' : 'stopped';
    label.textContent = d.state.toUpperCase();

    if (d.run_name) info.textContent = `run: ${d.run_name}`;
    if (d.state === 'stopped') info.textContent += ' (stopped)';

    document.getElementById('btn-start').disabled = state.running;
    document.getElementById('btn-stop').disabled  = !state.running;

    logLine(`detector ${d.state}${d.run_name ? ' — ' + d.run_name : ''}`,
            d.state === 'running' ? 'info' : 'warning');
}

function handleSweepStart(d) {
    state.sweepNum = d.sweep_num;
    state.minFreq  = d.min_freq / 1e6;
    state.maxFreq  = d.max_freq / 1e6;

    document.getElementById('sweep-label').textContent =
        `Sweep ${d.sweep_num + 1}`;
    document.getElementById('freq-range-label').textContent =
        `${state.minFreq.toFixed(0)}`;
    document.getElementById('freq-range-label-max').textContent =
        `${state.maxFreq.toFixed(0)} MHz`;

    resetSweepCanvas();
    logLine(`sweep ${d.sweep_num + 1} started — ${state.minFreq}–${state.maxFreq} MHz`);
}

function handleFreqUpdate(d) {
    state.currentFreq = d.freq / 1e6;
    document.getElementById('progress-bar').style.width = `${d.progress * 100}%`;
    document.getElementById('progress-label').textContent =
        `${state.currentFreq.toFixed(1)} MHz`;
}

function handleSpectrum(d) {
    const freqMHz = d.freq / 1e6;
    paintSweepColumn(freqMHz, d.power);
    paintWindowSpectrum(freqMHz, d.power);
}

function handlePlateauConfirmed(d) {
    const freqMHz = (d.freq / 1e6).toFixed(1);
    const bw      = d.bandwidth.toFixed(2);
    addRow(plateauTbody,
        [freqMHz + ' MHz', bw + ' MHz', `${d.hits}`, `#${d.sweep_num + 1}`],
        'confirmed');
    markPlateauOnSweep(parseFloat(freqMHz));
    logLine(`plateau confirmed — ${freqMHz} MHz  bw=${bw} MHz  hits=${d.hits}`);
}

function handleVideoConfirmed(d) {
    const freqMHz = (d.freq / 1e6).toFixed(1);
    addRow(detectionTbody,
        ['✓', freqMHz + ' MHz', d.classifier, d.score.toFixed(2), `#${d.sweep_num + 1}`],
        'video-confirmed');
    markVideoOnSweep(parseFloat(freqMHz), true);
    logLine(`VIDEO CONFIRMED — ${freqMHz} MHz  ${d.classifier}  score=${d.score.toFixed(2)}`, 'info');
}

function handleVideoRejected(d) {
    const freqMHz = (d.freq / 1e6).toFixed(1);
    addRow(detectionTbody,
        ['✗', freqMHz + ' MHz', d.classifier, d.score.toFixed(2), `#${d.sweep_num + 1}`],
        'video-rejected');
    markVideoOnSweep(parseFloat(freqMHz), false);
}

function handleError(d) {
    const freq = d.freq ? ` @ ${(d.freq / 1e6).toFixed(1)} MHz` : '';
    logLine(`${d.error_type}: ${d.message}${freq}`, 'error');
}

function handleSweepComplete(d) {
    logLine(`sweep ${d.sweep_num + 1} complete — ${d.plateaus} plateau(s)`, 'info');
    document.getElementById('progress-bar').style.width = '100%';
}

/* ------------------------------------------------------------------ */
/* SSE connection                                                       */
/* ------------------------------------------------------------------ */
const evtSource = new EventSource('/stream');

evtSource.onmessage = (e) => {
    let msg;
    try { msg = JSON.parse(e.data); } catch { return; }
    switch (msg.type) {
        case 'status':            handleStatus(msg.data);           break;
        case 'sweep_start':       handleSweepStart(msg.data);       break;
        case 'freq_update':       handleFreqUpdate(msg.data);       break;
        case 'spectrum':          handleSpectrum(msg.data);         break;
        case 'plateau_confirmed': handlePlateauConfirmed(msg.data); break;
        case 'plateau_rejected':  /* silently ignored in UI */       break;
        case 'video_confirmed':   handleVideoConfirmed(msg.data);   break;
        case 'video_rejected':    handleVideoRejected(msg.data);    break;
        case 'error':             handleError(msg.data);            break;
        case 'sweep_complete':    handleSweepComplete(msg.data);    break;
    }
};

evtSource.onerror = () => {
    logLine('SSE connection lost — reconnecting…', 'error');
    document.getElementById('status-dot').className = 'error';
};

/* ------------------------------------------------------------------ */
/* Controls                                                             */
/* ------------------------------------------------------------------ */
document.getElementById('device-select').addEventListener('change', function () {
    const show = this.value === 'file';
    document.getElementById('file-fields').style.display = show ? 'flex' : 'none';
});

document.getElementById('btn-start').addEventListener('click', async () => {
    const body = {
        device:      document.getElementById('device-select').value,
        file_path:   document.getElementById('file-path').value,
        metadata_path: document.getElementById('metadata-path').value,
        classifier:  document.getElementById('classifier-select').value,
        min_freq:    parseFloat(document.getElementById('min-freq').value),
        max_freq:    parseFloat(document.getElementById('max-freq').value),
        sweeps:      parseInt(document.getElementById('sweeps').value) || 0,
        verbosity:   parseInt(document.getElementById('verbosity').value),
        run_name:    document.getElementById('run-name').value || undefined,
    };
    const res = await fetch('/start', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body)
    });
    if (!res.ok) {
        const err = await res.json();
        logLine('Start failed: ' + (err.error || res.statusText), 'error');
    }
});

document.getElementById('btn-stop').addEventListener('click', async () => {
    await fetch('/stop', { method: 'POST' });
});

/* ------------------------------------------------------------------ */
/* Init                                                                 */
/* ------------------------------------------------------------------ */
window.addEventListener('resize', () => resizeCanvases());

// check current running state on load
fetch('/status').then(r => r.json()).then(d => {
    document.getElementById('btn-start').disabled = d.running;
    document.getElementById('btn-stop').disabled  = !d.running;
    if (d.running) {
        document.getElementById('status-dot').className = 'running';
        document.getElementById('status-label').textContent = 'RUNNING';
    }
});

// initial canvas size
requestAnimationFrame(() => {
    resizeCanvases();
    resetSweepCanvas();
});
