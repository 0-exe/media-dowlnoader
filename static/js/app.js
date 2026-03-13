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
  const downloadUrl = `/api/youtube/download?url=${encodeURIComponent(ytCurrentUrl)}&format=${encodeURIComponent(fmt)}`;

  ytDownload.disabled = true;
  ytProgress.classList.remove('hidden');

  triggerDownload(downloadUrl, () => {
    ytDownload.disabled = false;
    ytProgress.classList.add('hidden');
  });
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
  const downloadUrl = `/api/spotify/download?url=${encodeURIComponent(spCurrentUrl)}&format=${encodeURIComponent(fmt)}`;

  spDownload.disabled = true;
  spProgress.classList.remove('hidden');
  document.querySelector('#sp-progress .progress-label').textContent =
    'Preparing download… (this may take a while for playlists)';

  triggerDownload(downloadUrl, () => {
    spDownload.disabled = false;
    spProgress.classList.add('hidden');
  });
});

/* ── Download trigger helper ───────────────────────────────────────── */
/**
 * Trigger a file download using fetch() + Blob.
 * This approach reliably delivers files to the browser across all modern
 * browsers, unlike the hidden-iframe trick which many browsers silently
 * block or ignore for attachment responses.
 *
 * @param {string} url       Download endpoint URL
 * @param {Function} onDone  Called once the download completes or fails
 */
async function triggerDownload(url, onDone) {
  try {
    const res = await fetch(url);

    if (!res.ok) {
      // Server returned an error — try to parse the JSON message
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || `HTTP ${res.status}`);
    }

    // Extract filename from Content-Disposition header
    const disposition = res.headers.get('Content-Disposition');
    let filename = 'download';
    if (disposition) {
      const match = disposition.match(/filename="?([^"]+)"?/);
      if (match) filename = match[1];
    }

    const blob = await res.blob();
    const blobUrl = URL.createObjectURL(blob);

    const a = document.createElement('a');
    a.href = blobUrl;
    a.download = filename;
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    a.remove();

    // Revoke the blob URL after a short delay so the browser can start
    // the save-file dialog before the URL is invalidated.
    setTimeout(() => URL.revokeObjectURL(blobUrl), 60000);

    onDone && onDone();
  } catch (err) {
    showToast(err.message || 'Download failed', 'error');
    onDone && onDone();
  }
}
