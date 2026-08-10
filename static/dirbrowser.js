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

// Directory names can contain characters (&, <, >, ") that would break
// HTML if dropped into an attribute/text node unescaped -- this was the
// root cause of a real bug found via live testing 2026-08-10: rows used
// to build their onclick handler by string-concatenating
// JSON.stringify(path) directly inside an already double-quoted
// onclick="..." attribute, which JSON.stringify's own wrapping quotes
// broke for every single row, always (confirmed via a page-level JS
// syntax error, "Unexpected end of input"). Clicking a row to navigate
// into it, or the new per-row select button, never actually worked.
// data-path attributes (properly escaped) plus one delegated listener
// below avoids this whole class of bug instead of trying to get the
// quoting right by hand.
function escapeHtml(s) {
  const div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
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
      body.innerHTML = '<p class="hint" style="color:var(--danger-text);">' + escapeHtml(data.error) + '</p>';
      return;
    }
    pathEl.textContent = data.path;
    pathEl.dataset.path = data.path;
    const folderIcon = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z"/></svg>';
    const selectIcon = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
    let html = '';
    if (data.parent) {
      html += '<div class="dirbrowser-row"><span class="dirbrowser-row-name" data-action="open" data-path="' + escapeHtml(data.parent) + '">.. (up)</span></div>';
    }
    if (data.dirs.length === 0) {
      html += '<p class="hint" style="padding:0.5rem 0.6rem;">No subdirectories here. Use "Select this folder" below to pick the current one.</p>';
    }
    data.dirs.forEach(d => {
      const safePath = escapeHtml(d.path);
      const safeName = escapeHtml(d.name);
      html += '<div class="dirbrowser-row">' +
        '<span class="dirbrowser-row-name" data-action="open" data-path="' + safePath + '" title="Open ' + safeName + '">' + folderIcon + ' ' + safeName + '</span>' +
        '<button type="button" class="btn btn-icon dirbrowser-row-select" data-action="select" data-path="' + safePath + '" title="Select this folder" aria-label="Select ' + safeName + '">' + selectIcon + '</button>' +
        '</div>';
    });
    body.innerHTML = html;
  } catch (e) {
    body.innerHTML = '<p class="hint" style="color:var(--danger-text);">Couldn\'t browse: ' + escapeHtml(String(e)) + '</p>';
  }
}

// The modal's own HTML (including #dirbrowser-body) is always earlier in
// the document than this script tag -- see _dirbrowser_modal.html -- so
// this element already exists by the time this line runs, no need to
// wait for DOMContentLoaded.
document.getElementById('dirbrowser-body').addEventListener('click', (e) => {
  const el = e.target.closest('[data-action]');
  if (!el) return;
  const path = el.dataset.path;
  if (el.dataset.action === 'open') {
    loadDirBrowser(path);
  } else if (el.dataset.action === 'select') {
    selectDirBrowserPathDirect(path);
  }
});

function selectDirBrowserPath() {
  const pathEl = document.getElementById('dirbrowser-path');
  selectDirBrowserPathDirect(pathEl.dataset.path);
}

// Picks a listed folder directly, without first navigating into it --
// the per-row checkmark button. Confirmed via real user feedback
// 2026-08-10 that clicking a row to enter it, then having to find and
// click a separate "Select this folder" button in the footer to choose
// the folder you just entered, wasn't a discoverable way to actually
// pick something from the list.
function selectDirBrowserPathDirect(path) {
  const target = document.getElementById(__dirBrowserTargetId);
  if (target && path) {
    target.value = path;
    target.dispatchEvent(new Event('input'));
  }
  closeDirBrowser();
}
