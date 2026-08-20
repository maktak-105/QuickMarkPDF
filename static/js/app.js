(() => {
  // Mirrors thumbnail_panel.py's per-size (w, h) body dimensions -- see
  // _apply_size(). NUM_GUTTER_W/TAG_H/TEXT_H match its module constants.
  const NUM_GUTTER_W = 28;
  const TAG_H = 14;
  const TEXT_H = 14;
  const THUMB_SIZES = {
    small: { w: 80, h: 105 },
    medium: { w: 120, h: 155 },
    large: { w: 200, h: 260 },
  };
  const PREVIEW_RENDER_WIDTH = 900;  // base render resolution; on-screen size is scaled via currentZoom

  const statusEl = document.querySelector('#status');
  const pageList = document.querySelector('#page-list');
  const previewEl = document.querySelector('#preview');
  const pdfWorkspace = document.querySelector('#pdf-workspace');
  const markdownWorkspace = document.querySelector('#markdown-workspace');
  const markdownContent = document.querySelector('#markdown-content');

  const openButton = document.querySelector('#open-button');
  const splitButton = document.querySelector('#split-button');
  const rotateRightButton = document.querySelector('#rotate-right-button');
  const rotateLeftButton = document.querySelector('#rotate-left-button');
  const rotate180Button = document.querySelector('#rotate-180-button');
  const exportButton = document.querySelector('#export-button');
  const saveButton = document.querySelector('#save-button');
  const thumbSizeButtons = {
    small: document.querySelector('#thumb-size-small'),
    medium: document.querySelector('#thumb-size-medium'),
    large: document.querySelector('#thumb-size-large'),
  };

  let pages = [];
  // Multi-select (Ctrl toggles one item, Shift selects a range from the
  // last click) mirrors the Python baseline's thumbnail panel, since
  // rotate/delete both operate on "every selected page" there.
  // primaryIndex is whichever item last became selected -- that's the one
  // the preview pane shows.
  let selectedIndices = new Set();
  let primaryIndex = -1;
  let anchorIndex = -1;
  let dragFromIndex = -1;
  let canUndo = false;
  let currentMode = 'pdf';
  let currentThumbSize = 'medium';

  // Preview zoom/pan state -- mirrors MainWindow's current_zoom / _wheel_mode /
  // eventFilter() panning. wheelMode: 'zoom' (default; wheel=zoom, right-drag=pan)
  // or 'scroll' (wheel=native vertical scroll, right-drag=zoom).
  let wheelMode = 'zoom';
  let currentZoom = 1.0;
  let previewNaturalWidth = 0;
  let previewNaturalHeight = 0;
  let panning = false;
  let panStartX = 0;
  let panStartY = 0;
  let hScrollStart = 0;
  let vScrollStart = 0;
  let zoomDragStart = 1.0;

  const hasBridge = () => Boolean(window.chrome?.webview);
  const post = (payload) => {
    if (hasBridge()) window.chrome.webview.postMessage(JSON.stringify(payload));
  };

  // Compact Markdown -> HTML converter. Covers headings, paragraphs,
  // bold/italic, inline code, fenced code blocks, blockquotes (recursive),
  // simple (non-nested) bullet/numbered lists, links, images, and
  // horizontal rules -- deliberately not a full CommonMark implementation.
  // Mermaid/MathJax rendering and tables are not implemented; see
  // plans/2026-08-20_*.md for what's deferred. Escapes HTML in the source
  // first, so raw HTML embedded in a Markdown file renders as literal text
  // rather than executing -- a safe simplification, not a Python-parity
  // feature (the Python baseline's `Markdown` package allows raw HTML
  // passthrough).
  function escapeHtml(text) {
    return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function renderInline(text) {
    let out = escapeHtml(text);
    out = out.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, '<img alt="$1" src="$2">');
    out = out.replace(/\[([^\]]*)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    out = out.replace(/__([^_]+)__/g, '<strong>$1</strong>');
    out = out.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    out = out.replace(/`([^`]+)`/g, '<code>$1</code>');
    return out;
  }

  function markdownToHtml(source) {
    const lines = source.replace(/\r\n?/g, '\n').split('\n');
    const html = [];
    let i = 0;
    let paragraphLines = [];
    let list = null;  // { type: 'ul'|'ol', items: [] }

    const flushParagraph = () => {
      if (paragraphLines.length) {
        html.push('<p>' + renderInline(paragraphLines.join(' ')) + '</p>');
        paragraphLines = [];
      }
    };
    const flushList = () => {
      if (list) {
        html.push(`<${list.type}>` + list.items.map((item) => `<li>${renderInline(item)}</li>`).join('') +
          `</${list.type}>`);
        list = null;
      }
    };

    while (i < lines.length) {
      const line = lines[i];

      if (/^```/.test(line)) {
        flushParagraph();
        flushList();
        const codeLines = [];
        i += 1;
        while (i < lines.length && !/^```/.test(lines[i])) {
          codeLines.push(lines[i]);
          i += 1;
        }
        i += 1;
        html.push('<pre><code>' + escapeHtml(codeLines.join('\n')) + '</code></pre>');
        continue;
      }

      const heading = line.match(/^(#{1,6})\s+(.*)$/);
      if (heading) {
        flushParagraph();
        flushList();
        const level = heading[1].length;
        html.push(`<h${level}>${renderInline(heading[2].trim())}</h${level}>`);
        i += 1;
        continue;
      }

      if (/^(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
        flushParagraph();
        flushList();
        html.push('<hr>');
        i += 1;
        continue;
      }

      if (/^>\s?/.test(line)) {
        flushParagraph();
        flushList();
        const quoted = [];
        while (i < lines.length && /^>\s?/.test(lines[i])) {
          quoted.push(lines[i].replace(/^>\s?/, ''));
          i += 1;
        }
        html.push('<blockquote>' + markdownToHtml(quoted.join('\n')) + '</blockquote>');
        continue;
      }

      const bullet = line.match(/^[-*+]\s+(.*)$/);
      if (bullet) {
        flushParagraph();
        if (!list || list.type !== 'ul') {
          flushList();
          list = { type: 'ul', items: [] };
        }
        list.items.push(bullet[1]);
        i += 1;
        continue;
      }

      const numbered = line.match(/^\d+\.\s+(.*)$/);
      if (numbered) {
        flushParagraph();
        if (!list || list.type !== 'ol') {
          flushList();
          list = { type: 'ol', items: [] };
        }
        list.items.push(numbered[1]);
        i += 1;
        continue;
      }

      if (line.trim() === '') {
        flushParagraph();
        flushList();
        i += 1;
        continue;
      }

      paragraphLines.push(line.trim());
      i += 1;
    }
    flushParagraph();
    flushList();
    return html.join('\n');
  }

  function setStatus(text) {
    statusEl.textContent = text;
  }

  function sourceFileName(path) {
    const parts = path.split(/[\\/]/);
    return parts[parts.length - 1] || path;
  }

  function selectedIndicesSorted() {
    return Array.from(selectedIndices).sort((a, b) => a - b);
  }

  function updateToolbarEnabled() {
    // Rotate/split/export/save are PDF-only -- in Markdown mode there is no
    // page selection at all, so these are simply unusable (matches the
    // Python baseline hiding/disabling the same controls outside PDF mode).
    // Delete/Undo are keyboard-only in the Python baseline (no toolbar
    // button at all -- see main_window.py's _create_toolbar, which adds
    // delete_page_action/undo_action via addAction(), not toolbar.addAction()),
    // so there is no button state to manage for them here.
    const isPdfMode = currentMode === 'pdf';
    const hasSelection = isPdfMode && selectedIndices.size > 0;
    rotateRightButton.disabled = !hasSelection;
    rotateLeftButton.disabled = !hasSelection;
    rotate180Button.disabled = !hasSelection;
    splitButton.disabled = !hasSelection;
    exportButton.disabled = !isPdfMode || pages.length === 0;
    saveButton.disabled = !isPdfMode || pages.length === 0;
    for (const btn of Object.values(thumbSizeButtons)) btn.disabled = !isPdfMode;
  }

  function setMode(mode) {
    currentMode = mode;
    const isPdfMode = mode === 'pdf';
    pdfWorkspace.hidden = !isPdfMode;
    markdownWorkspace.hidden = isPdfMode;
    updateToolbarEnabled();
  }

  function applySelectionToDom() {
    document.querySelectorAll('.page-item').forEach((el) => {
      el.classList.toggle('selected', selectedIndices.has(Number(el.dataset.pageIndex)));
    });
  }

  function selectPage(index, event) {
    if (index < 0 || index >= pages.length) return;
    const ctrl = Boolean(event && (event.ctrlKey || event.metaKey));
    const shift = Boolean(event && event.shiftKey);

    if (shift && anchorIndex >= 0) {
      const lo = Math.min(anchorIndex, index);
      const hi = Math.max(anchorIndex, index);
      selectedIndices = new Set();
      for (let i = lo; i <= hi; i += 1) selectedIndices.add(i);
      primaryIndex = index;
    } else if (ctrl) {
      if (selectedIndices.has(index)) {
        selectedIndices.delete(index);
        if (primaryIndex === index) {
          const remaining = selectedIndicesSorted();
          primaryIndex = remaining.length > 0 ? remaining[remaining.length - 1] : -1;
        }
      } else {
        selectedIndices.add(index);
        primaryIndex = index;
      }
      anchorIndex = index;
    } else {
      selectedIndices = new Set([index]);
      primaryIndex = index;
      anchorIndex = index;
    }

    applySelectionToDom();
    updateToolbarEnabled();
    if (primaryIndex >= 0 && primaryIndex < pages.length) {
      post({ type: 'render_page', page_index: primaryIndex, width: PREVIEW_RENDER_WIDTH });
    }
  }

  function paintImage(target, message) {
    const binary = atob(message.pixels);
    const bytes = new Uint8ClampedArray(binary.length);
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    const canvas = document.createElement('canvas');
    canvas.width = message.width;
    canvas.height = message.height;
    canvas.getContext('2d').putImageData(new ImageData(bytes, message.width, message.height), 0, 0);
    if (target instanceof HTMLCanvasElement) {
      target.width = message.width;
      target.height = message.height;
      target.getContext('2d').drawImage(canvas, 0, 0);
    } else {
      target.src = canvas.toDataURL('image/png');
    }
  }

  // Right-click context menu (open/close-file, rotate, cut out, export,
  // delete) -- mirrors the Python baseline's thumbnail right-click menu
  // (ThumbnailPanel._show_context_menu).
  let contextMenuEl = null;
  function closeContextMenu() {
    if (contextMenuEl) {
      contextMenuEl.remove();
      contextMenuEl = null;
    }
  }
  function showContextMenu(x, y, sourcePath) {
    closeContextMenu();
    const menu = document.createElement('div');
    menu.className = 'context-menu';
    menu.style.left = `${x}px`;
    menu.style.top = `${y}px`;

    const items = [
      ['右90°回転', () => doRotate(90)],
      ['左90°回転', () => doRotate(-90)],
      ['180°回転', () => doRotate(180)],
      ['PDF切り出し...', doSplit],
      ['画像を切り出し (PNG/JPG)...', () => doExport(selectedIndicesSorted())],
      ['ページを削除', doDelete],
      ['このファイルを閉じる', () => post({ type: 'close_document', path: sourcePath })],
    ];
    items.forEach(([label, handler]) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.textContent = label;
      btn.addEventListener('click', () => {
        handler();
        closeContextMenu();
      });
      menu.appendChild(btn);
    });

    document.body.appendChild(menu);
    contextMenuEl = menu;
  }
  document.addEventListener('click', closeContextMenu);
  document.addEventListener('scroll', closeContextMenu, true);

  // Mirrors ThumbnailPanel._get_qpixmap_from_page's canvas layout: a
  // NUM_GUTTER_W-wide left gutter showing the page's position in the whole
  // document, beside a body column of [filename tag / page image / "p.N"
  // original-page-index label].
  function buildPageItem(page, index, docPageNo) {
    const item = document.createElement('div');
    item.className = 'page-item';
    item.dataset.pageIndex = String(index);
    item.draggable = true;

    const gutter = document.createElement('div');
    gutter.className = 'page-gutter';
    gutter.textContent = String(docPageNo);
    item.appendChild(gutter);

    const body = document.createElement('div');
    body.className = 'page-body';

    const tag = document.createElement('div');
    tag.className = 'page-tag';
    tag.textContent = sourceFileName(page.path);
    body.appendChild(tag);

    const canvas = document.createElement('canvas');
    canvas.className = 'page-thumbnail';
    body.appendChild(canvas);

    const number = document.createElement('div');
    number.className = 'page-number';
    number.textContent = `p.${index + 1}`;
    body.appendChild(number);

    item.appendChild(body);

    item.addEventListener('click', (event) => selectPage(index, event));
    item.addEventListener('contextmenu', (event) => {
      event.preventDefault();
      if (!selectedIndices.has(index)) selectPage(index, event);
      showContextMenu(event.clientX, event.clientY, page.path);
    });

    item.addEventListener('dragstart', (event) => {
      dragFromIndex = index;
      event.dataTransfer.effectAllowed = 'move';
    });
    item.addEventListener('dragover', (event) => {
      event.preventDefault();
      item.classList.add('drag-over');
    });
    item.addEventListener('dragleave', () => item.classList.remove('drag-over'));
    item.addEventListener('drop', (event) => {
      event.preventDefault();
      item.classList.remove('drag-over');
      if (dragFromIndex < 0 || dragFromIndex === index) return;
      // Dropping onto the item currently at `index` should land the moved
      // page exactly there. If it was dragged from earlier in the list,
      // removing it first shifts everything after it left by one, so the
      // target's post-removal position is index - 1, not index.
      const order = Array.from({ length: pages.length }, (_, i) => i);
      const [moved] = order.splice(dragFromIndex, 1);
      const insertAt = dragFromIndex < index ? index - 1 : index;
      order.splice(insertAt, 0, moved);
      post({ type: 'reorder_pages', order });
      dragFromIndex = -1;
    });

    return item;
  }

  function renderPageList(data) {
    pages = data.pages || [];
    canUndo = Boolean(data.can_undo);
    setMode('pdf');

    if (pages.length === 0) {
      pageList.className = 'empty';
      pageList.replaceChildren();
      pageList.textContent = 'PDFを開くとページ一覧を表示します。';
      selectedIndices = new Set();
      primaryIndex = -1;
      anchorIndex = -1;
      previewEl.replaceChildren();
      const welcome = document.createElement('div');
      welcome.className = 'welcome';
      welcome.innerHTML = '<h1>QuickMarkPDF</h1><p>「開く」からPDFを選択してください。</p>';
      previewEl.appendChild(welcome);
      updateToolbarEnabled();
      return;
    }

    pageList.className = '';
    pageList.replaceChildren();
    const thumbWidth = THUMB_SIZES[currentThumbSize].w;
    pages.forEach((page, index) => {
      pageList.appendChild(buildPageItem(page, index, index + 1));
      post({ type: 'render_page', page_index: index, width: NUM_GUTTER_W + thumbWidth });
    });

    // The page count/positions may have just changed (delete/reorder/undo);
    // keep whatever selection still fits, defaulting to the first page if
    // nothing survived.
    selectedIndices = new Set(Array.from(selectedIndices).filter((i) => i < pages.length));
    if (primaryIndex < 0 || primaryIndex >= pages.length) {
      primaryIndex = selectedIndicesSorted()[0] ?? 0;
    }
    if (selectedIndices.size === 0) selectedIndices.add(primaryIndex);
    applySelectionToDom();
    updateToolbarEnabled();
    post({ type: 'render_page', page_index: primaryIndex, width: PREVIEW_RENDER_WIDTH });
  }

  // ── サムネイルサイズ切替（ツールバー2段目） ──
  function setThumbSize(size) {
    if (!THUMB_SIZES[size] || size === currentThumbSize) return;
    currentThumbSize = size;
    for (const [name, btn] of Object.entries(thumbSizeButtons)) {
      btn.classList.toggle('checked', name === size);
    }
    const { w, h } = THUMB_SIZES[size];
    document.documentElement.style.setProperty('--thumb-w', `${w}px`);
    document.documentElement.style.setProperty('--thumb-max-h', `${h - TAG_H - TEXT_H}px`);
    // Mirrors ThumbnailPanel._apply_size: panel width = gutter + body + scrollbar/border allowance.
    document.documentElement.style.setProperty('--panel-w', `${NUM_GUTTER_W + w + 24}px`);
    if (pages.length > 0) {
      // Re-render every thumbnail at the new width; renderPageList() already
      // does this same walk on open/delete/reorder/undo.
      const thumbWidth = THUMB_SIZES[size].w;
      pages.forEach((_page, index) => {
        post({ type: 'render_page', page_index: index, width: NUM_GUTTER_W + thumbWidth });
      });
    }
    const sizeName = { small: '小', medium: '中', large: '大' }[size];
    setStatus(`サムネイルサイズを「${sizeName}」に変更しました`);
  }
  thumbSizeButtons.small.addEventListener('click', () => setThumbSize('small'));
  thumbSizeButtons.medium.addEventListener('click', () => setThumbSize('medium'));
  thumbSizeButtons.large.addEventListener('click', () => setThumbSize('large'));
  setThumbSize('medium');  // apply the CSS custom properties for the default size

  // ── サムネイル欄・プレビュー欄の境界(QSplitter相当) ──
  // Python版はQSplitterでこの境界をドラッグ幅変更できる。setThumbSize()が
  // 設定する --panel-w はあくまで初期値/既定値で、ここでのドラッグはそれを
  // 独立して上書きする(Python版もサムネイルサイズとスプリッタ位置は別々の状態)。
  const panelSplitter = document.querySelector('#panel-splitter');
  let splitterDragging = false;
  let splitterStartX = 0;
  let splitterStartWidth = 0;
  panelSplitter.addEventListener('mousedown', (event) => {
    splitterDragging = true;
    splitterStartX = event.clientX;
    splitterStartWidth = document.querySelector('.thumbnail-panel').getBoundingClientRect().width;
    panelSplitter.classList.add('dragging');
    document.body.style.cursor = 'col-resize';
    event.preventDefault();
  });
  window.addEventListener('mousemove', (event) => {
    if (!splitterDragging) return;
    const dx = event.clientX - splitterStartX;
    const minWidth = NUM_GUTTER_W + THUMB_SIZES.small.w;
    const maxWidth = pdfWorkspace.clientWidth - 200;  // プレビュー側に最低200pxは残す
    const newWidth = Math.max(minWidth, Math.min(splitterStartWidth + dx, maxWidth));
    document.documentElement.style.setProperty('--panel-w', `${newWidth}px`);
  });
  window.addEventListener('mouseup', () => {
    if (!splitterDragging) return;
    splitterDragging = false;
    panelSplitter.classList.remove('dragging');
    document.body.style.cursor = '';
  });

  // ── プレビュー ズーム / パン（PreviewLabel + eventFilter 相当） ──
  function applyPreviewZoom() {
    const img = previewEl.querySelector('img');
    if (!img || !previewNaturalWidth) return;
    const w = previewNaturalWidth * currentZoom;
    const h = previewNaturalHeight * currentZoom;
    img.style.width = `${w}px`;
    img.style.height = `${h}px`;
    // .preview centers its content via flex align-items/justify-content, but
    // centering an element LARGER than its overflow:auto container gives it
    // a negative offset that the default scroll position (0,0) lands in the
    // middle of -- for a tall page with content only near the top, this
    // showed as a blank preview (confirmed via qa/_diag_preview.py: img
    // top was -280px at scrollTop 0). Qt's QScrollArea doesn't have this
    // problem -- it only centers content that fits; oversized content just
    // starts at (0,0) -- so switch to flex-start on whichever axis actually
    // overflows to match that behavior instead of CSS's default centering.
    previewEl.style.alignItems = h > previewEl.clientHeight ? 'flex-start' : 'center';
    previewEl.style.justifyContent = w > previewEl.clientWidth ? 'flex-start' : 'center';
  }

  function fitPreviewToWidth() {
    if (!previewNaturalWidth) return;
    const viewportWidth = previewEl.clientWidth - 30;  // margin for scrollbar, matches _fit_to_width
    if (viewportWidth > 0) {
      currentZoom = Math.max(0.05, Math.min(viewportWidth / previewNaturalWidth, 8.0));
    } else {
      currentZoom = 1.0;
    }
    applyPreviewZoom();
  }

  previewEl.addEventListener('wheel', (event) => {
    if (currentMode !== 'pdf' || !previewNaturalWidth) return;
    if (wheelMode === 'zoom') {
      const factor = event.deltaY < 0 ? 1.15 : 1 / 1.15;
      currentZoom = Math.max(0.1, Math.min(currentZoom * factor, 8.0));
      applyPreviewZoom();
      event.preventDefault();
    }
    // "scroll" mode: let the browser's native scroll happen.
  }, { passive: false });

  previewEl.addEventListener('mousedown', (event) => {
    if (event.button !== 2 || currentMode !== 'pdf') return;  // right button only
    panning = true;
    panStartX = event.clientX;
    panStartY = event.clientY;
    if (wheelMode === 'zoom') {
      hScrollStart = previewEl.scrollLeft;
      vScrollStart = previewEl.scrollTop;
    } else {
      zoomDragStart = currentZoom;
    }
    previewEl.style.cursor = 'grabbing';
    event.preventDefault();
  });
  window.addEventListener('mousemove', (event) => {
    if (!panning) return;
    const dx = event.clientX - panStartX;
    const dy = event.clientY - panStartY;
    if (wheelMode === 'zoom') {
      previewEl.scrollLeft = hScrollStart - dx;
      previewEl.scrollTop = vScrollStart - dy;
    } else if (previewNaturalWidth) {
      const factor = Math.pow(1.005, dy);  // drag down (+y) = zoom in
      currentZoom = Math.max(0.1, Math.min(zoomDragStart * factor, 8.0));
      applyPreviewZoom();
    }
  });
  window.addEventListener('mouseup', (event) => {
    if (event.button !== 2 || !panning) return;
    panning = false;
    previewEl.style.cursor = '';
  });
  previewEl.addEventListener('contextmenu', (event) => event.preventDefault());

  // ── 「設定」メニュー & 環境設定モーダル ──
  const settingsMenu = document.querySelector('#settings-menu');
  const settingsDropdown = document.querySelector('#settings-dropdown');
  const menuLabel = settingsMenu.querySelector('.menu-label');
  menuLabel.addEventListener('click', (event) => {
    event.stopPropagation();
    settingsDropdown.hidden = !settingsDropdown.hidden;
  });
  document.addEventListener('click', () => { settingsDropdown.hidden = true; });

  const preferencesOverlay = document.querySelector('#preferences-overlay');
  const preferencesItem = document.querySelector('#preferences-item');
  preferencesItem.addEventListener('click', () => {
    settingsDropdown.hidden = true;
    document.querySelector(`input[name="wheel-mode"][value="${wheelMode}"]`).checked = true;
    preferencesOverlay.hidden = false;
  });
  document.querySelector('#preferences-cancel').addEventListener('click', () => {
    preferencesOverlay.hidden = true;
  });
  document.querySelector('#preferences-ok').addEventListener('click', () => {
    const checked = document.querySelector('input[name="wheel-mode"]:checked');
    if (checked) wheelMode = checked.value;
    preferencesOverlay.hidden = true;
  });

  function doOpen() {
    if (!hasBridge()) {
      setStatus('WebView2ブリッジ未接続（ブラウザプレビュー）');
      return;
    }
    setStatus('PDFバックエンドへ接続中…');
    post({ type: 'open_pdf' });
  }
  function doRotate(degrees) {
    if (selectedIndices.size === 0) return;
    post({ type: 'rotate_pages', indices: selectedIndicesSorted(), degrees });
  }
  function doDelete() {
    if (selectedIndices.size === 0) return;
    post({ type: 'delete_pages', indices: selectedIndicesSorted() });
  }
  function doSplit() {
    if (selectedIndices.size === 0) return;
    post({ type: 'split_pdf', indices: selectedIndicesSorted() });
  }
  function doUndo() {
    post({ type: 'undo_edit' });
  }
  function doExport(indices) {
    if (pages.length === 0) return;
    post({ type: 'export_images', indices: indices || [], dpi: 150 });
  }
  function doSave() {
    if (pages.length === 0) return;
    post({ type: 'save_pdf' });
  }

  openButton.addEventListener('click', doOpen);
  rotateRightButton.addEventListener('click', () => doRotate(90));
  rotateLeftButton.addEventListener('click', () => doRotate(-90));
  rotate180Button.addEventListener('click', () => doRotate(180));
  splitButton.addEventListener('click', doSplit);
  exportButton.addEventListener('click', () => doExport());
  saveButton.addEventListener('click', doSave);

  // Keyboard shortcuts, matching the Python baseline: Delete removes the
  // selection, Ctrl+Z undoes, Ctrl+S saves, Ctrl+O opens. Delete/Undo are
  // keyboard-only in the Python baseline (main_window.py adds them via
  // self.addAction(), never toolbar.addAction()) -- there is deliberately
  // no toolbar button for either. Ignored while focus is in a text field
  // (none exist in this UI today, but this is cheap insurance against a
  // future one swallowing Delete/typed text).
  document.addEventListener('keydown', (event) => {
    const target = event.target;
    const typing = target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable);
    if (typing) return;

    if (event.key === 'Delete') {
      event.preventDefault();
      doDelete();
    } else if (event.ctrlKey && !event.shiftKey && !event.altKey && event.key.toLowerCase() === 'z') {
      event.preventDefault();
      doUndo();
    } else if (event.ctrlKey && !event.shiftKey && !event.altKey && event.key.toLowerCase() === 's') {
      event.preventDefault();
      doSave();
    } else if (event.ctrlKey && !event.shiftKey && !event.altKey && event.key.toLowerCase() === 'o') {
      event.preventDefault();
      doOpen();
    }
  });

  if (hasBridge()) {
    window.chrome.webview.addEventListener('message', (event) => {
      // The C++ side replies via PostWebMessageAsString (not
      // PostWebMessageAsJson), so event.data arrives as raw JSON text, not
      // an already-parsed object -- without this parse, every branch below
      // silently no-ops forever since e.g. "someJsonString".type is always
      // undefined. (This exact gap is CPP_PORT_POSTMORTEM.md's root cause
      // for "PDFを開く" never having worked in the first attempt.)
      let data;
      try {
        data = JSON.parse(event.data);
      } catch (err) {
        return;
      }
      if (!data) return;

      if (data.type === 'backend_status') {
        setStatus(data.message);
      }

      if (data.type === 'pdf_opened') {
        if (typeof data.loaded_files === 'number') {
          let message = `${data.loaded_files}件のファイルを読み込みました（${data.page_count}ページ）`;
          if (data.failed_files && data.failed_files.length > 0) {
            message += ` / 読み込めなかったファイル: ${data.failed_files.join(', ')}`;
          }
          setStatus(message);
        }
        renderPageList(data);
      }

      if (data.type === 'document_state') {
        renderPageList(data);
      }

      if (data.type === 'markdown_opened') {
        markdownContent.innerHTML = markdownToHtml(data.content || '');
        setMode('markdown');
      }

      if (data.type === 'page_rendered') {
        if (data.width === PREVIEW_RENDER_WIDTH) {
          let img = previewEl.querySelector('img');
          if (!img) {
            previewEl.replaceChildren();
            img = document.createElement('img');
            previewEl.appendChild(img);
          }
          paintImage(img, data);
          previewNaturalWidth = data.width;
          previewNaturalHeight = data.height;
          fitPreviewToWidth();
          // A fresh page should always open showing its top, not wherever
          // the previous page happened to be scrolled to.
          previewEl.scrollTop = 0;
          previewEl.scrollLeft = 0;
        } else {
          const canvas = pageList.querySelector(`canvas[data-page-index="${data.page_index}"]`) ||
            pageList.querySelector(`.page-item[data-page-index="${data.page_index}"] canvas`);
          if (canvas) paintImage(canvas, data);
        }
      }
    });
  } else {
    setStatus('WebView2ブリッジ未接続（ブラウザプレビュー）');
  }
})();
