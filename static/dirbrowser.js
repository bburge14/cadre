let __dirBrowserTargetId = null;

function openDirBrowser(targetInputId, startPath) {
  __dirBrowserTargetId = targetInputId;
  document.getElementById('dirbrowser-overlay').style.display = 'flex';
  const target = document.getElementById(targetInputId);
  loadDirBrowser(startPath || (target && target.value) || '');
}

function closeDirBrowser() {
  document.getElementById('dirbrowser-overlay').style.display = 'none';
}

async function loadDirBrowser(path) {
  const body = document.getElementById('dirbrowser-body');
  const pathEl = document.getElementById('dirbrowser-path');
  body.innerHTML = '<p class="hint">Loading…</p>';
  try {
    const url = '/api/browse-dirs' + (path ? '?path=' + encodeURIComponent(path) : '');
    const res = await fetch(url);
    const data = await res.json();
    if (!data.ok) {
      body.innerHTML = '<p class="hint" style="color:var(--danger-text);">' + data.error + '</p>';
      return;
    }
    pathEl.textContent = data.path;
    pathEl.dataset.path = data.path;
    let html = '';
    if (data.parent) {
      html += '<div class="dirbrowser-row" onclick="loadDirBrowser(' + JSON.stringify(data.parent) + ')">.. (up)</div>';
    }
    if (data.dirs.length === 0) {
      html += '<p class="hint" style="padding:0.5rem 0.6rem;">No subdirectories here.</p>';
    }
    data.dirs.forEach(d => {
      html += '<div class="dirbrowser-row" onclick="loadDirBrowser(' + JSON.stringify(d.path) + ')">' + d.name + '</div>';
    });
    body.innerHTML = html;
  } catch (e) {
    body.innerHTML = '<p class="hint" style="color:var(--danger-text);">Couldn\'t browse: ' + e + '</p>';
  }
}

function selectDirBrowserPath() {
  const pathEl = document.getElementById('dirbrowser-path');
  const target = document.getElementById(__dirBrowserTargetId);
  if (target && pathEl.dataset.path) {
    target.value = pathEl.dataset.path;
    target.dispatchEvent(new Event('input'));
  }
  closeDirBrowser();
}
