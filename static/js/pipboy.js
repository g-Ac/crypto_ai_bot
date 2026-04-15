/* pipboy.js — Helpers for Pip-Boy Dashboard */

/* ── Format Helpers ── */
function fmtUsd(v) {
  if (v == null) return '$0.00';
  var n = parseFloat(v);
  var sign = n >= 0 ? '+' : '';
  return sign + '$' + Math.abs(n).toLocaleString('en-US', {
    minimumFractionDigits: 2, maximumFractionDigits: 2
  });
}

function fmtPct(v) {
  if (v == null) return '0.00%';
  var n = parseFloat(v);
  var sign = n >= 0 ? '+' : '';
  return sign + n.toFixed(2) + '%';
}

function fmtTemp(c) {
  return c != null ? parseFloat(c).toFixed(1) + '\u00b0C' : '--';
}

function fmtUptime(seconds) {
  if (!seconds) return '--';
  var d = Math.floor(seconds / 86400);
  var h = Math.floor((seconds % 86400) / 3600);
  var m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return d + 'd ' + h + 'h';
  if (h > 0) return h + 'h ' + m + 'm';
  return m + 'm';
}

/* ── Keyboard Shortcuts ── */
document.addEventListener('keydown', function(e) {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
  var tabs = {'1':'status','2':'trades','3':'analysis','4':'logs','5':'system'};
  if (tabs[e.key]) {
    window.location.href = '/pip/' + tabs[e.key];
  }
});

/* ── SSE Log Terminal ── */
var LOG_MAX_LINES = 500;
var LOG_COLORS = {
  'ERR':     'var(--pip-red)',
  'ERROR':   'var(--pip-red)',
  'WARN':    'var(--pip-green-bright)',
  'WARNING': 'var(--pip-green-bright)',
  'INFO':    'var(--pip-green-mid)',
  'DEBUG':   'var(--pip-green-dim)',
  'PUMP':    'var(--pip-green-bright)'
};

function detectLogLevel(line) {
  var upper = line.toUpperCase();
  if (upper.indexOf('ERROR') !== -1 || upper.indexOf(' ERR ') !== -1) return 'ERR';
  if (upper.indexOf('WARNING') !== -1 || upper.indexOf(' WARN ') !== -1) return 'WARN';
  if (upper.indexOf('PUMP') !== -1) return 'PUMP';
  if (upper.indexOf('DEBUG') !== -1) return 'DEBUG';
  return 'INFO';
}

function initLogTerminal(containerId, sseUrl) {
  var container = document.getElementById(containerId);
  if (!container) return null;

  var paused = false;
  var es = new EventSource(sseUrl);

  es.addEventListener('log', function(evt) {
    if (paused) return;

    var line = evt.data;
    var level = detectLogLevel(line);
    var color = LOG_COLORS[level] || 'var(--pip-green-mid)';

    var div = document.createElement('div');
    div.className = 'log-line';
    div.style.color = color;
    div.textContent = line;
    container.appendChild(div);

    /* Buffer limit — remove oldest lines */
    while (container.childElementCount > LOG_MAX_LINES) {
      container.removeChild(container.firstChild);
    }

    /* Auto-scroll to bottom */
    container.scrollTop = container.scrollHeight;
  });

  es.onerror = function() {
    var div = document.createElement('div');
    div.className = 'log-line';
    div.style.color = 'var(--pip-red-dim)';
    div.textContent = '> CONNECTION LOST — RECONNECTING...';
    container.appendChild(div);
  };

  return {
    pause:  function() { paused = true; },
    resume: function() { paused = false; },
    toggle: function() { paused = !paused; return paused; },
    close:  function() { es.close(); }
  };
}
