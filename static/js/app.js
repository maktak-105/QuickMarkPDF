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
  let dragIndices = [];
  // Row the dragged block will land at (thumbnail_panel.py's _insert_row):
  // -1 = no valid drop target yet. Computed from cursor Y vs. the hovered
  // item's vertical center in dragover, NOT simply "the hovered item's own
  // index" -- always using the hovered index made every drop onto the
  // adjacent next item a no-op (it reinserted the page at the exact
  // position it started from), which is why reordering looked broken.
  let pendingInsertRow = -1;
  let dragOverEl = null;
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

  // クロップ範囲選択(PreviewLabel.get_pdf_clip_rect相当)。cropSelectionは
  // previewNaturalWidth/Height基準(=ズーム前のレンダリング座標)の矩形。
  // ページ寸法(PDFポイント)はrender_pageの応答から得る -- previewNaturalWidthピクセルが
  // pageWidthPtポイントに相当するので、比率(pageWidthPt/previewNaturalWidth)で変換する。
  let pageWidthPt = 0;
  let pageHeightPt = 0;
  let cropSelection = null;  // {x0,y0,x1,y1} in previewNaturalWidth/Height px space, or null
  let cropDragging = false;
  let cropDragOriginX = 0;
  let cropDragOriginY = 0;

  const hasBridge = () => Boolean(window.chrome?.webview);
  const post = (payload) => {
    if (hasBridge()) window.chrome.webview.postMessage(JSON.stringify(payload));
  };

  // Compact Markdown -> HTML converter. Covers headings, paragraphs,
  // bold/italic, inline code, fenced code blocks (incl. ```mermaid blocks),
  // blockquotes (recursive), simple (non-nested) bullet/numbered lists,
  // links, images, GFM tables, inline/display math ($..$/$$..$$), and
  // horizontal rules -- deliberately not a full CommonMark implementation.
  // Escapes HTML in the source first, so raw HTML embedded in a Markdown
  // file renders as literal text rather than executing -- a safe
  // simplification, not a Python-parity feature (the Python baseline's
  // `Markdown` package allows raw HTML passthrough).

  // Math protection: replaces $$..$$ (display) and $..$ (inline) segments
  // with opaque tokens before markdownToHtml runs, so bold/italic/code
  // regexes and HTML-escaping never touch the LaTeX source, then restores
  // the raw math text after conversion (mirrors markdown_manager.py's
  // _protect_math/_restore_math_tokens token-swap approach). Skips fenced
  // code blocks entirely, same as the Python version. MathJax's tex-svg.js
  // itself scans the final DOM text for the $/$$ delimiters at render time.
  let mathTokenCounter = 0;
  function protectMath(source) {
    const tokens = new Map();
    const makeToken = (kind, content) => {
      const token = `@@QMPDFMATH${mathTokenCounter}@@`;
      mathTokenCounter += 1;
      tokens.set(token, { kind, content });
      return token;
    };
    const replaceMath = (segment) => segment
      .replace(/(?<!\\)\$\$([\s\S]+?)(?<!\\)\$\$/g, (m, inner) => makeToken('display', `$$${inner}$$`))
      .replace(/(?<!\\)\$(?!\$)([^$\n]+?)(?<!\\)\$/g, (m, inner) => makeToken('inline', `$${inner}$`));
    const parts = source.split(/(^```[\w-]*\s*$[\s\S]*?^```\s*$)/m);
    return { text: parts.map((part, idx) => (idx % 2 === 0 ? replaceMath(part) : part)).join(''), tokens };
  }
  function restoreMathTokens(html, tokens) {
    let restored = html;
    tokens.forEach((value, token) => {
      if (value.kind === 'display') {
        restored = restored.split(`<p>${token}</p>`).join(`<div class="math">${value.content}</div>`);
      }
      restored = restored.split(token).join(value.content);
    });
    return restored;
  }
  function renderMarkdownDocument(source) {
    const { text, tokens } = protectMath(source);
    return restoreMathTokens(markdownToHtml(text), tokens);
  }

  // Mermaid initialization mirrors markdown_manager.py's inline <script>
  // (startOnLoad: false, securityLevel: 'loose', theme: 'default', run
  // against every .mermaid element) and MathJax's typesetPromise() call.
  // Both libraries load as `defer` <script src> tags (see bundle_html.py),
  // so by the time this runs (only ever triggered by a markdown_opened
  // message, always after the page's own initial load) window.mermaid/
  // window.MathJax are already defined -- guarded with `if` anyway in case
  // vendor/ assets are missing from a given build (matches Python's own
  // asset_urls.exists() fallback to plain, unenhanced Markdown).
  async function enhanceMarkdownRender() {
    try {
      if (window.mermaid) {
        window.mermaid.initialize({ startOnLoad: false, securityLevel: 'loose', theme: 'default' });
        await window.mermaid.run({ querySelector: '.markdown-content .mermaid' });
      }
      if (window.MathJax && window.MathJax.typesetPromise) {
        await window.MathJax.typesetPromise();
      }
    } catch (err) {
      console.warn('Markdown enhancement render failed:', err);
    }
  }
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

  // GFM table row splitting: strips one optional leading/trailing pipe,
  // then splits on '|'. A cell containing an escaped pipe ('\|') is not
  // supported (matches this converter's general "compact, not full
  // CommonMark" scope).
  function splitTableRow(line) {
    let trimmed = line.trim();
    if (trimmed.startsWith('|')) trimmed = trimmed.slice(1);
    if (trimmed.endsWith('|')) trimmed = trimmed.slice(0, -1);
    return trimmed.split('|').map((c) => c.trim());
  }
  function isTableSeparatorRow(line) {
    if (!/\|/.test(line) && !/^:?-+:?$/.test(line.trim())) return false;
    const cells = splitTableRow(line);
    return cells.length > 0 && cells.every((c) => /^:?-{1,}:?$/.test(c));
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
        const langMatch = line.match(/^```([\w-]*)/);
        const lang = langMatch ? langMatch[1].toLowerCase() : '';
        const codeLines = [];
        i += 1;
        while (i < lines.length && !/^```/.test(lines[i])) {
          codeLines.push(lines[i]);
          i += 1;
        }
        i += 1;
        if (lang === 'mermaid') {
          html.push('<pre class="mermaid">' + escapeHtml(codeLines.join('\n')) + '</pre>');
        } else {
          html.push('<pre><code>' + escapeHtml(codeLines.join('\n')) + '</code></pre>');
        }
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

      if (/\|/.test(line) && i + 1 < lines.length && isTableSeparatorRow(lines[i + 1])) {
        flushParagraph();
        flushList();
        const headerCells = splitTableRow(line);
        const aligns = splitTableRow(lines[i + 1]).map((c) => {
          const left = c.startsWith(':');
          const right = c.endsWith(':');
          if (left && right) return 'center';
          if (right) return 'right';
          if (left) return 'left';
          return '';
        });
        i += 2;
        const bodyRows = [];
        while (i < lines.length && lines[i].trim() !== '' && /\|/.test(lines[i])) {
          bodyRows.push(splitTableRow(lines[i]));
          i += 1;
        }
        const alignAttr = (idx) => (aligns[idx] ? ` style="text-align:${aligns[idx]}"` : '');
        const theadHtml = '<thead><tr>' +
          headerCells.map((c, idx) => `<th${alignAttr(idx)}>${renderInline(c)}</th>`).join('') +
          '</tr></thead>';
        const tbodyHtml = '<tbody>' + bodyRows.map((row) => '<tr>' +
          headerCells.map((_, idx) => `<td${alignAttr(idx)}>${renderInline(row[idx] || '')}</td>`).join('') +
          '</tr>').join('') + '</tbody>';
        html.push('<table>' + theadHtml + tbodyHtml + '</table>');
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
    // 保存はPDF/Markdown両方で使える(Python版のsave_action同様、
    // save_pdf()がcurrent_modeで分岐する) -- Markdownモードでは
    // 常に有効(モードに遷移できた時点で文書が読み込まれている)。
    saveButton.disabled = isPdfMode ? pages.length === 0 : false;
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
    // Measure off-screen first (visibility:hidden keeps layout so
    // getBoundingClientRect() returns real dimensions), then clamp the
    // requested (x, y) so the menu never renders past the window's right/
    // bottom edge -- previously a right-click near the bottom of a long
    // thumbnail list opened a menu whose lower items landed outside the
    // WebView2 window and were unreachable.
    menu.style.visibility = 'hidden';
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

    const margin = 4;
    const rect = menu.getBoundingClientRect();
    const clampedLeft = Math.max(margin, Math.min(x, window.innerWidth - rect.width - margin));
    const clampedTop = Math.max(margin, Math.min(y, window.innerHeight - rect.height - margin));
    menu.style.left = `${clampedLeft}px`;
    menu.style.top = `${clampedTop}px`;
    menu.style.visibility = '';
  }
  document.addEventListener('click', closeContextMenu);
  document.addEventListener('scroll', closeContextMenu, true);

  // Mirrors thumbnail_panel.py's _compute_new_order exactly: move
  // draggedIndices (old flat indices) as a contiguous block to targetPos,
  // preserving their original relative order -- generalizes the old
  // single-item-only drag math to a multi-selection drag.
  function computeReorderedOrder(pagesLength, draggedIndices, targetPos) {
    const currentOrder = Array.from({ length: pagesLength }, (_, i) => i);
    const draggedSet = new Set(draggedIndices);
    targetPos = Math.min(targetPos, currentOrder.length);
    const remaining = [];
    let removedBeforeTarget = 0;
    currentOrder.forEach((pageIdx, i) => {
      if (draggedSet.has(pageIdx)) {
        if (i < targetPos) removedBeforeTarget += 1;
        return;
      }
      remaining.push(pageIdx);
    });
    let insertAt = targetPos - removedBeforeTarget;
    insertAt = Math.max(0, Math.min(insertAt, remaining.length));
    const draggedInOrder = currentOrder.filter((idx) => draggedSet.has(idx));
    return [...remaining.slice(0, insertAt), ...draggedInOrder, ...remaining.slice(insertAt)];
  }

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
    // page.source_page is the page's ORIGINAL index within its source file
    // (webview_main.cpp's pages_json(), from PageInfo::original_page_index)
    // -- matches thumbnail_panel.py's f"p.{info.original_page_index + 1}".
    // Using index+1 here (the position in the CURRENT edited document, same
    // value the gutter number already shows) made both numbers identical
    // and meaningless for any document that had pages reordered, merged
    // from multiple files, or partially deleted.
    number.textContent = `p.${page.source_page + 1}`;
    body.appendChild(number);

    item.appendChild(body);

    item.addEventListener('click', (event) => selectPage(index, event));
    item.addEventListener('contextmenu', (event) => {
      event.preventDefault();
      if (!selectedIndices.has(index)) selectPage(index, event);
      showContextMenu(event.clientX, event.clientY, page.path);
    });

    item.addEventListener('dragstart', (event) => {
      // Drag the whole multi-selection when the dragged item is part of it
      // (matches thumbnail_panel.py's dragEnterEvent: "drag whatever is
      // currently selected"), otherwise just the one item under the cursor.
      dragIndices = (selectedIndices.has(index) && selectedIndices.size > 1)
        ? selectedIndicesSorted() : [index];
      pendingInsertRow = -1;
      event.dataTransfer.effectAllowed = 'move';
    });
    item.addEventListener('dragend', () => {
      // Fires even when the drop landed outside any valid target (e.g. the
      // drag was cancelled) -- without this, a stale insertion-line class
      // could keep highlighting an item from an aborted drag.
      if (dragOverEl) { dragOverEl.classList.remove('drag-over-above', 'drag-over-below'); dragOverEl = null; }
      dragIndices = [];
      pendingInsertRow = -1;
    });
    item.addEventListener('dragover', (event) => {
      event.preventDefault();
      // Mirrors thumbnail_panel.py's _get_insertion_row: below the hovered
      // item's vertical center -> land after it (row+1), above -> before it
      // (row). Without this split, dropping anywhere on an item could only
      // ever mean "insert before", so dragging a page onto its own very
      // next neighbor recomputed the exact same position it started at.
      const rect = item.getBoundingClientRect();
      const below = event.clientY > rect.top + rect.height / 2;
      pendingInsertRow = below ? index + 1 : index;
      if (dragOverEl && dragOverEl !== item) {
        dragOverEl.classList.remove('drag-over-above', 'drag-over-below');
      }
      item.classList.toggle('drag-over-below', below);
      item.classList.toggle('drag-over-above', !below);
      dragOverEl = item;
    });
    item.addEventListener('dragleave', () => {
      item.classList.remove('drag-over-above', 'drag-over-below');
      if (dragOverEl === item) dragOverEl = null;
    });
    item.addEventListener('drop', (event) => {
      event.preventDefault();
      item.classList.remove('drag-over-above', 'drag-over-below');
      dragOverEl = null;
      if (dragIndices.length === 0 || pendingInsertRow < 0) { dragIndices = []; pendingInsertRow = -1; return; }
      const order = computeReorderedOrder(pages.length, dragIndices, pendingInsertRow);
      post({ type: 'reorder_pages', order });
      dragIndices = [];
      pendingInsertRow = -1;
    });

    return item;
  }

  // Dropping in the empty space below the last item (Python: itemAt(pos) is
  // None -> insertion row = count()) -- only acts when the event target is
  // the list container itself, since a drop over any item is already
  // handled (and pendingInsertRow already set) by that item's own listener.
  pageList.addEventListener('dragover', (event) => {
    if (event.target !== pageList) return;
    event.preventDefault();
    pendingInsertRow = pages.length;
    if (dragOverEl) { dragOverEl.classList.remove('drag-over-above', 'drag-over-below'); dragOverEl = null; }
  });
  pageList.addEventListener('drop', (event) => {
    if (event.target !== pageList) return;
    event.preventDefault();
    if (dragIndices.length === 0 || pendingInsertRow < 0) { dragIndices = []; pendingInsertRow = -1; return; }
    const order = computeReorderedOrder(pages.length, dragIndices, pendingInsertRow);
    post({ type: 'reorder_pages', order });
    dragIndices = [];
    pendingInsertRow = -1;
  });

  function renderPageList(data) {
    pages = data.pages || [];
    canUndo = Boolean(data.can_undo);
    // setMode('pdf') used to live here unconditionally, which meant ANY
    // document_state message -- including the read-only echo "get_state"
    // triggers (see dispatch_message in webview_main.cpp) -- forced the UI
    // out of Markdown mode even when nothing PDF-related had happened.
    // Found via qa/check_ui_behaviors_cpp.py: querying state while in
    // Markdown mode silently snapped the view back to the (empty) PDF
    // workspace. Only the pdf_opened handler (a real "a PDF was just
    // loaded" event) should switch mode now.

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
  // localStorage経由でセッションをまたいで永続化する(Python版のQSettings相当)。
  // WebView2は固定のユーザーデータフォルダ(%TEMP%\QuickMarkPDF_WVData)を毎回
  // 再利用するため、localStorageは通常の再起動間で維持される。
  function setThumbSize(size, persist = true) {
    if (!THUMB_SIZES[size] || size === currentThumbSize) return;
    currentThumbSize = size;
    if (persist) {
      try { localStorage.setItem('quickmarkpdf.thumbSize', size); } catch (e) { /* ignore */ }
    }
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
  {
    let savedThumbSize = 'medium';
    try { savedThumbSize = localStorage.getItem('quickmarkpdf.thumbSize') || 'medium'; } catch (e) { /* ignore */ }
    currentThumbSize = null;  // force setThumbSize to actually apply, even if savedThumbSize === 'medium'
    setThumbSize(savedThumbSize in THUMB_SIZES ? savedThumbSize : 'medium', false);
  }

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

  // ── クロップ範囲選択(PreviewLabel相当。左ドラッグでラバーバンド選択) ──
  function clearCropSelection() {
    cropSelection = null;
    const overlay = document.querySelector('#crop-overlay');
    if (overlay) overlay.remove();
  }
  function renderCropOverlay(naturalRect) {
    const img = previewEl.querySelector('img');
    if (!img) return;
    let overlay = document.querySelector('#crop-overlay');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = 'crop-overlay';
      previewEl.appendChild(overlay);
    }
    // img.offsetLeft/Top is relative to previewEl (its offsetParent, since
    // .preview has position:relative) and -- unlike getBoundingClientRect --
    // is unaffected by previewEl's current scroll position, which is exactly
    // what an absolutely-positioned sibling that should scroll along with
    // the image needs.
    overlay.style.left = `${img.offsetLeft + naturalRect.x0 * currentZoom}px`;
    overlay.style.top = `${img.offsetTop + naturalRect.y0 * currentZoom}px`;
    overlay.style.width = `${(naturalRect.x1 - naturalRect.x0) * currentZoom}px`;
    overlay.style.height = `${(naturalRect.y1 - naturalRect.y0) * currentZoom}px`;
  }
  // previewEl自体はスクロールコンテナで、img自体もcurrentZoomでスケールされているため、
  // オーバーレイの位置は「imgの左上からのnatural(ズーム前)座標」で管理し、img自体を
  // 親要素として使う(previewEl直下だとスクロール位置分のズレが出るため)。
  previewEl.addEventListener('mousedown', (event) => {
    if (event.button !== 0 || currentMode !== 'pdf' || !previewNaturalWidth) return;
    const img = previewEl.querySelector('img');
    if (!img) return;
    const rect = img.getBoundingClientRect();
    const nx = (event.clientX - rect.left) / currentZoom;
    const ny = (event.clientY - rect.top) / currentZoom;
    if (nx < 0 || ny < 0 || nx > previewNaturalWidth || ny > previewNaturalHeight) {
      clearCropSelection();
      return;
    }
    cropDragging = true;
    cropDragOriginX = nx;
    cropDragOriginY = ny;
    clearCropSelection();
    event.preventDefault();
  });
  window.addEventListener('mousemove', (event) => {
    if (!cropDragging) return;
    const img = previewEl.querySelector('img');
    if (!img) return;
    const rect = img.getBoundingClientRect();
    const nx = Math.max(0, Math.min((event.clientX - rect.left) / currentZoom, previewNaturalWidth));
    const ny = Math.max(0, Math.min((event.clientY - rect.top) / currentZoom, previewNaturalHeight));
    const naturalRect = {
      x0: Math.min(cropDragOriginX, nx), y0: Math.min(cropDragOriginY, ny),
      x1: Math.max(cropDragOriginX, nx), y1: Math.max(cropDragOriginY, ny),
    };
    renderCropOverlay(naturalRect);
  });
  window.addEventListener('mouseup', (event) => {
    if (event.button !== 0 || !cropDragging) return;
    cropDragging = false;
    const overlay = document.querySelector('#crop-overlay');
    const w = overlay ? parseFloat(overlay.style.width) : 0;
    const h = overlay ? parseFloat(overlay.style.height) : 0;
    // PythonのmouseReleaseEventと同じ閾値(5px、ズーム後の画面ピクセル基準):
    // ドラッグ幅がほぼ0ならクリックとして扱い選択解除する。
    if (w > 5 && h > 5 && overlay) {
      const img = previewEl.querySelector('img');
      const offsetLeft = img ? img.offsetLeft : 0;
      const offsetTop = img ? img.offsetTop : 0;
      const left = parseFloat(overlay.style.left) - offsetLeft;
      const top = parseFloat(overlay.style.top) - offsetTop;
      cropSelection = {
        x0: left / currentZoom, y0: top / currentZoom,
        x1: (left + w) / currentZoom, y1: (top + h) / currentZoom,
      };
    } else {
      clearCropSelection();
    }
  });

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
    if (checked) {
      wheelMode = checked.value;
      try { localStorage.setItem('quickmarkpdf.wheelMode', wheelMode); } catch (e) { /* ignore */ }
    }
    preferencesOverlay.hidden = true;
  });
  try {
    const savedWheelMode = localStorage.getItem('quickmarkpdf.wheelMode');
    if (savedWheelMode === 'zoom' || savedWheelMode === 'scroll') wheelMode = savedWheelMode;
  } catch (e) { /* ignore */ }

  // ── 「ヘルプ」メニュー、使い方モーダル、バージョン情報モーダル ──
  const helpMenu = document.querySelector('#help-menu');
  const helpDropdown = document.querySelector('#help-dropdown');
  helpMenu.querySelector('.menu-label').addEventListener('click', (event) => {
    event.stopPropagation();
    helpDropdown.hidden = !helpDropdown.hidden;
  });
  document.addEventListener('click', () => { helpDropdown.hidden = true; });

  const helpOverlay = document.querySelector('#help-overlay');
  document.querySelector('#help-item').addEventListener('click', () => {
    helpDropdown.hidden = true;
    helpOverlay.hidden = false;
  });
  document.querySelector('#help-close').addEventListener('click', () => {
    helpOverlay.hidden = true;
  });

  const aboutOverlay = document.querySelector('#about-overlay');
  document.querySelector('#about-item').addEventListener('click', () => {
    helpDropdown.hidden = true;
    aboutOverlay.hidden = false;
  });
  document.querySelector('#about-close').addEventListener('click', () => {
    aboutOverlay.hidden = true;
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
  // ── 画像エクスポート ダイアログ(Python版 ExportDialog相当) ──
  const exportOverlay = document.querySelector('#export-overlay');
  const exportScopeAll = document.querySelector('#export-scope-all');
  const exportScopeSelected = document.querySelector('#export-scope-selected');
  const exportTotalCount = document.querySelector('#export-total-count');
  const exportSelectedCount = document.querySelector('#export-selected-count');
  const exportAreaAll = document.querySelector('#export-area-all');
  const exportAreaCrop = document.querySelector('#export-area-crop');
  const exportFormat = document.querySelector('#export-format');
  const exportDpiPreset = document.querySelector('#export-dpi-preset');
  const exportDpiCustom = document.querySelector('#export-dpi-custom');
  const exportQualityRow = document.querySelector('#export-quality-row');
  const exportQuality = document.querySelector('#export-quality');
  const exportQualityLabel = document.querySelector('#export-quality-label');
  const exportDir = document.querySelector('#export-dir');
  const exportPrefix = document.querySelector('#export-prefix');
  const exportExample = document.querySelector('#export-example');
  let exportPendingIndices = [];
  // Remembered across dialog opens within this session -- mirrors
  // main_window.py's self._export_settings (format/dpi/jpeg_quality only;
  // scope/area/dir/prefix stay contextual, recomputed per open).
  const rememberedExportSettings = { format: 'png', dpi: 150, jpeg_quality: 90 };

  function updateExportExample() {
    const prefix = exportPrefix.value.trim() || 'page';
    const fmt = exportFormat.value === 'jpg' ? 'jpg' : 'png';
    exportExample.textContent = `出力例: ${prefix}_0001.${fmt}  ${prefix}_0002.${fmt}  ...`;
  }
  function onExportFormatChanged() {
    const isJpg = exportFormat.value === 'jpg';
    exportQuality.disabled = !isJpg;
    exportQualityRow.style.opacity = isJpg ? '1' : '.5';
    updateExportExample();
  }
  function onExportDpiPresetChanged() {
    const isCustom = exportDpiPreset.value === '0';
    exportDpiCustom.disabled = !isCustom;
    if (isCustom) { exportDpiCustom.focus(); exportDpiCustom.select(); }
  }
  function currentExportDpi() {
    return exportDpiPreset.value === '0' ? (parseInt(exportDpiCustom.value, 10) || 150) : parseInt(exportDpiPreset.value, 10);
  }
  exportFormat.addEventListener('change', onExportFormatChanged);
  exportDpiPreset.addEventListener('change', onExportDpiPresetChanged);
  exportQuality.addEventListener('input', () => { exportQualityLabel.textContent = exportQuality.value; });
  exportPrefix.addEventListener('input', updateExportExample);
  exportDir.addEventListener('input', updateExportExample);
  document.querySelector('#export-browse').addEventListener('click', () => {
    post({ type: 'browse_export_folder' });
  });
  document.querySelector('#export-cancel').addEventListener('click', () => { exportOverlay.hidden = true; });
  document.querySelector('#export-run').addEventListener('click', () => {
    const scope = (exportScopeSelected.checked && !exportScopeSelected.disabled) ? 'selected' : 'all';
    const indices = scope === 'selected' ? exportPendingIndices : pages.map((_p, i) => i);
    const fmt = exportFormat.value === 'jpg' ? 'jpg' : 'png';
    const dpi = currentExportDpi();
    const quality = parseInt(exportQuality.value, 10) || 90;
    rememberedExportSettings.format = fmt;
    rememberedExportSettings.dpi = dpi;
    rememberedExportSettings.jpeg_quality = quality;
    const payload = {
      type: 'export_images', indices, dpi, fmt, jpeg_quality: quality,
      output_dir: exportDir.value.trim(), prefix: exportPrefix.value.trim() || 'page',
    };
    const useCrop = exportAreaCrop.checked && !exportAreaCrop.disabled;
    // pageWidthPt/previewNaturalWidth converts the selection from rendered-
    // preview pixels to PDF points (page-space, pre-rotation-scale) --
    // matches PreviewLabel.get_pdf_clip_rect()'s 1.5px/pt conversion, just
    // with our own render width instead of Python's fixed 1.5x.
    if (useCrop && cropSelection && pageWidthPt > 0 && previewNaturalWidth > 0) {
      const ptPerPx = pageWidthPt / previewNaturalWidth;
      payload.crop = [
        cropSelection.x0 * ptPerPx, cropSelection.y0 * ptPerPx,
        cropSelection.x1 * ptPerPx, cropSelection.y1 * ptPerPx,
      ];
    }
    exportOverlay.hidden = true;
    post(payload);
  });

  function doExport(indices) {
    if (pages.length === 0) return;
    const sel = indices && indices.length ? indices : selectedIndicesSorted();
    exportPendingIndices = sel;

    exportTotalCount.textContent = String(pages.length);
    exportSelectedCount.textContent = String(sel.length);
    exportScopeSelected.disabled = sel.length === 0;
    if (sel.length > 0) { exportScopeSelected.checked = true; } else { exportScopeAll.checked = true; }

    const hasCrop = Boolean(cropSelection);
    exportAreaCrop.disabled = !hasCrop;
    exportAreaCrop.checked = hasCrop;
    exportAreaAll.checked = !hasCrop;

    exportFormat.value = rememberedExportSettings.format;
    const standardDpi = ['72', '150', '300'];
    if (standardDpi.includes(String(rememberedExportSettings.dpi))) {
      exportDpiPreset.value = String(rememberedExportSettings.dpi);
      exportDpiCustom.disabled = true;
    } else {
      exportDpiPreset.value = '0';
      exportDpiCustom.disabled = false;
      exportDpiCustom.value = String(rememberedExportSettings.dpi);
    }
    exportQuality.value = String(rememberedExportSettings.jpeg_quality);
    exportQualityLabel.textContent = String(rememberedExportSettings.jpeg_quality);
    onExportFormatChanged();

    exportDir.value = '';
    exportPrefix.value = 'page';
    updateExportExample();
    exportOverlay.hidden = false;
    // Backend fills in a sensible folder/prefix suggestion (source file's
    // own directory, suggest_export_basename()) once it replies -- see the
    // 'export_defaults' message handler below.
    post({ type: 'get_export_defaults', indices: sel.length > 0 ? sel : pages.map((_p, i) => i) });
  }
  function doSave() {
    if (currentMode === 'markdown') {
      post({ type: 'save_markdown_pdf' });
      return;
    }
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
    } else if ((event.key === 'ArrowDown' || event.key === 'ArrowUp') &&
               target && target.closest('.thumbnail-panel') &&
               currentMode === 'pdf' && pages.length > 0) {
      // Thumbnail panel is a scrollable region (overflow-y: auto), so
      // Chromium implicitly focuses it on click and Up/Down would otherwise
      // just scroll it -- switch the page selection instead, matching how
      // clicking a neighboring thumbnail already behaves.
      event.preventDefault();
      const delta = event.key === 'ArrowDown' ? 1 : -1;
      const nextIndex = Math.max(0, Math.min(pages.length - 1, primaryIndex + delta));
      selectPage(nextIndex);
      const nextEl = pageList.querySelector(`.page-item[data-page-index="${nextIndex}"]`);
      if (nextEl) nextEl.scrollIntoView({ block: 'nearest' });
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
        setMode('pdf');
        renderPageList(data);
      }

      if (data.type === 'document_state') {
        renderPageList(data);
      }

      if (data.type === 'markdown_opened') {
        markdownContent.innerHTML = renderMarkdownDocument(data.content || '');
        setMode('markdown');
        enhanceMarkdownRender();
      }

      if (data.type === 'export_defaults') {
        if (!exportOverlay.hidden) {
          exportDir.value = data.output_dir || '';
          exportPrefix.value = data.prefix || 'page';
          updateExportExample();
        }
      }

      if (data.type === 'folder_picked') {
        if (data.path) { exportDir.value = data.path; updateExportExample(); }
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
          pageWidthPt = data.page_width_pt || 0;
          pageHeightPt = data.page_height_pt || 0;
          // Matches PreviewLabel.set_base_pixmap: a freshly displayed page
          // (even if it's the same page re-rendered after rotate/undo)
          // clears any crop selection from before.
          clearCropSelection();
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
