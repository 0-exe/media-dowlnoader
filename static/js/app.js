/* ── Direct-stream toggle (persisted in localStorage) ────────────── */
const directStreamToggle = document.getElementById('direct-stream-toggle');
directStreamToggle.checked = localStorage.getItem('directStream') === 'true';
directStreamToggle.addEventListener('change', () => {
  localStorage.setItem('directStream', directStreamToggle.checked);
});
function isDirectStream() { return directStreamToggle.checked; }

/* ── Tab switching ─────────────────────────────────────────────────── */
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => {
      t.classList.remove('active');
      t.setAttribute('aria-selected', 'false');
    });
    document.querySelectorAll('.panel').forEach(p => {
      p.classList.remove('active');
      p.classList.add('hidden');
    });
    tab.classList.add('active');
    tab.setAttribute('aria-selected', 'true');
    const target = document.getElementById(tab.dataset.tab);
    target.classList.add('active');
    target.classList.remove('hidden');
  });
});

/* ── Toast system ──────────────────────────────────────────────────── */
function showToast(message, type = 'info', duration = 4000) {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `
    <span>${escHtml(message)}</span>
    <button class="toast-close" aria-label="Close">×</button>
  `;
  toast.querySelector('.toast-close').addEventListener('click', () => removeToast(toast));
  container.appendChild(toast);
  if (duration > 0) setTimeout(() => removeToast(toast), duration);
  return toast;
}

function removeToast(toast) {
  toast.style.animation = 'fadeOut .3s ease forwards';
  setTimeout(() => toast.remove(), 300);
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/* ── Generic fetch-with-error-handling ─────────────────────────────── */
async function apiPost(endpoint, body) {
  const res = await fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

/* ═══════════════════════════════════════════════════════════════════════
   YouTube
═══════════════════════════════════════════════════════════════════════ */
const ytUrl      = document.getElementById('yt-url');
const ytFetch    = document.getElementById('yt-fetch');
const ytCard     = document.getElementById('yt-card');
const ytThumb    = document.getElementById('yt-thumb');
const ytTitle    = document.getElementById('yt-title');
const ytMeta     = document.getElementById('yt-meta');
const ytFormat   = document.getElementById('yt-format');
const ytDownload = document.getElementById('yt-download');
const ytProgress = document.getElementById('yt-progress');

let ytCurrentUrl = '';

ytUrl.addEventListener('keydown', e => { if (e.key === 'Enter') ytFetch.click(); });

ytFetch.addEventListener('click', async () => {
  const url = ytUrl.value.trim();
  if (!url) { showToast('Please enter a YouTube URL', 'error'); return; }

  ytFetch.disabled = true;
  ytFetch.textContent = 'Fetching…';
  ytCard.classList.add('hidden');
  ytProgress.classList.add('hidden');

  try {
    const info = await apiPost('/api/youtube/info', { url });
    ytCurrentUrl = info.url;

    ytThumb.src = info.thumbnail || '';
    ytThumb.onerror = () => { ytThumb.src = ''; };
    ytTitle.textContent = info.title;
    ytMeta.textContent = `${info.uploader || ''}  •  ${info.duration || ''}`;

    ytFormat.innerHTML = '';
    const groups = {};
    (info.formats || []).forEach(f => {
      const grp = f.group || 'Other';
      if (!groups[grp]) groups[grp] = [];
      groups[grp].push(f);
    });
    Object.keys(groups).forEach(grp => {
      const optgroup = document.createElement('optgroup');
      optgroup.label = grp;
      groups[grp].forEach(f => {
        const opt = document.createElement('option');
        opt.value = f.value;
        opt.textContent = f.label;
        optgroup.appendChild(opt);
      });
      ytFormat.appendChild(optgroup);
    });

    ytCard.classList.remove('hidden');
  } catch (err) {
    showToast(err.message || 'Failed to fetch video info', 'error');
  } finally {
    ytFetch.disabled = false;
    ytFetch.textContent = 'Fetch';
  }
});

ytDownload.addEventListener('click', () => {
  if (!ytCurrentUrl) return;
  const fmt = ytFormat.value;
  const onDone = () => {
    ytDownload.disabled = false;
    ytProgress.classList.add('hidden');
  };

  ytDownload.disabled = true;
  ytProgress.classList.remove('hidden');
  const label = document.querySelector('#yt-progress .progress-label');

  if (isDirectStream()) {
    label.textContent = 'Downloading (direct stream)…';
    const params = new URLSearchParams({ url: ytCurrentUrl, format: fmt });
    window.location.href = `/api/youtube/download?${params}`;
    setTimeout(onDone, 3000);
  } else {
    startJobDownload(
      '/api/youtube/start',
      { url: ytCurrentUrl, format: fmt },
      label,
      onDone,
    );
  }
});

/* ═══════════════════════════════════════════════════════════════════════
   Spotify
═══════════════════════════════════════════════════════════════════════ */
const spUrl      = document.getElementById('sp-url');
const spFetch    = document.getElementById('sp-fetch');
const spCard     = document.getElementById('sp-card');
const spThumb    = document.getElementById('sp-thumb');
const spTitle    = document.getElementById('sp-title');
const spMeta     = document.getElementById('sp-meta');
const spTracks   = document.getElementById('sp-tracks');
const spFormat   = document.getElementById('sp-format');
const spDownload = document.getElementById('sp-download');
const spProgress = document.getElementById('sp-progress');

let spCurrentUrl = '';

spUrl.addEventListener('keydown', e => { if (e.key === 'Enter') spFetch.click(); });

spFetch.addEventListener('click', async () => {
  const url = spUrl.value.trim();
  if (!url) { showToast('Please enter a Spotify URL', 'error'); return; }

  spFetch.disabled = true;
  spFetch.textContent = 'Fetching…';
  spCard.classList.add('hidden');
  spProgress.classList.add('hidden');

  try {
    const info = await apiPost('/api/spotify/info', { url });
    spCurrentUrl = info.url;

    spThumb.src = info.thumbnail || '';
    spThumb.onerror = () => { spThumb.src = ''; };
    spTitle.textContent = info.name;
    spMeta.textContent = `${info.artist || ''}  •  ${info.album || ''}`;

    if (info.type !== 'track') {
      spTracks.textContent = `${info.track_count} track${info.track_count !== 1 ? 's' : ''} — downloads as ZIP`;
    } else {
      spTracks.textContent = '';
    }

    spCard.classList.remove('hidden');
  } catch (err) {
    showToast(err.message || 'Failed to fetch Spotify info', 'error');
  } finally {
    spFetch.disabled = false;
    spFetch.textContent = 'Fetch';
  }
});

spDownload.addEventListener('click', () => {
  if (!spCurrentUrl) return;
  const fmt = spFormat.value;
  const onDone = () => {
    spDownload.disabled = false;
    spProgress.classList.add('hidden');
  };

  spDownload.disabled = true;
  spProgress.classList.remove('hidden');
  const label = document.querySelector('#sp-progress .progress-label');

  if (isDirectStream()) {
    label.textContent = 'Downloading (direct stream)…';
    const params = new URLSearchParams({ url: spCurrentUrl, format: fmt });
    window.location.href = `/api/spotify/download?${params}`;
    setTimeout(onDone, 3000);
  } else {
    label.textContent = 'Preparing download… (this may take a while for playlists)';
    startJobDownload(
      '/api/spotify/start',
      { url: spCurrentUrl, format: fmt },
      label,
      onDone,
    );
  }
});

/* ── Download helpers ──────────────────────────────────────────────── */
/**
 * Start a background download job, poll for completion, then navigate the
 * browser directly to the download URL so the file streams straight to disk.
 *
 * Using window.location for the final step (instead of fetch+blob) avoids:
 *   • Loading the entire file into JavaScript memory.
 *   • Reverse-proxy read-timeout issues (the file is already on disk when
 *     the browser connects to /api/jobs/<id>/download).
 *
 * @param {string}   startUrl  POST endpoint that starts the job
 * @param {object}   body      JSON body for the start request
 * @param {Element}  label     Progress label element to update
 * @param {Function} onDone    Called once the download starts or fails
 */
async function startJobDownload(startUrl, body, label, onDone) {
  // How often to poll (ms) and max total wait (ms)
  const POLL_INTERVAL = 2000;
  const MAX_WAIT_MS = 10 * 60 * 1000; // 10 minutes
  const DOWNLOAD_START_DELAY_MS = 1500;

  try {
    if (label) label.textContent = 'Starting download…';

    const startRes = await fetch(startUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const startData = await startRes.json().catch(() => ({}));
    if (!startRes.ok) throw new Error(startData.error || `HTTP ${startRes.status}`);

    const jobId = startData.job_id;
    if (!jobId) throw new Error('No job ID returned by server');

    // Poll /api/jobs/<id>/status until ready or error
    const deadline = Date.now() + MAX_WAIT_MS;
    let dots = 0;
    while (Date.now() < deadline) {
      await new Promise(r => setTimeout(r, POLL_INTERVAL));

      const statusRes = await fetch(`/api/jobs/${jobId}/status`);
      const statusData = await statusRes.json().catch(() => ({}));

      if (!statusRes.ok) throw new Error(statusData.error || `HTTP ${statusRes.status}`);

      if (statusData.status === 'error') {
        throw new Error(statusData.error || 'Download failed on server');
      }

      if (statusData.status === 'ready') {
        if (label) label.textContent = 'Download ready — saving file…';
        // Navigate directly: browser streams file to disk, no memory buffering,
        // and no long-lived connection through the proxy during the yt-dlp phase.
        window.location.href = `/api/jobs/${jobId}/download`;
        // Give the browser a moment to start the download before re-enabling the button.
        setTimeout(() => onDone && onDone(), DOWNLOAD_START_DELAY_MS);
        return;
      }

      // Still pending — update label with animated dots
      dots = (dots + 1) % 4;
      if (label) label.textContent = `Preparing download${'.'.repeat(dots)}`;
    }

    throw new Error('Download timed out while waiting for server');
  } catch (err) {
    showToast(err.message || 'Download failed', 'error');
    onDone && onDone();
  }
}
