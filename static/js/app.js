(() => {
  const THUMBNAIL_WIDTH = 160;
  const PREVIEW_WIDTH = 900;

  const statusEl = document.querySelector('#status');
  const pageList = document.querySelector('#page-list');
  const previewEl = document.querySelector('#preview');

  const openButton = document.querySelector('#open-button');
  const rotateRightButton = document.querySelector('#rotate-right-button');
  const rotateLeftButton = document.querySelector('#rotate-left-button');
  const rotate180Button = document.querySelector('#rotate-180-button');
  const deleteButton = document.querySelector('#delete-button');
  const undoButton = document.querySelector('#undo-button');
  const exportButton = document.querySelector('#export-button');
  const saveButton = document.querySelector('#save-button');

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

  const hasBridge = () => Boolean(window.chrome?.webview);
  const post = (payload) => {
    if (hasBridge()) window.chrome.webview.postMessage(JSON.stringify(payload));
  };

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
    const hasSelection = selectedIndices.size > 0;
    rotateRightButton.disabled = !hasSelection;
    rotateLeftButton.disabled = !hasSelection;
    rotate180Button.disabled = !hasSelection;
    deleteButton.disabled = !hasSelection;
    exportButton.disabled = pages.length === 0;
    saveButton.disabled = pages.length === 0;
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
      post({ type: 'render_page', page_index: primaryIndex, width: PREVIEW_WIDTH });
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

  function buildPageItem(page, index) {
    const item = document.createElement('div');
    item.className = 'page-item';
    item.dataset.pageIndex = String(index);
    item.draggable = true;

    const tag = document.createElement('div');
    tag.className = 'page-tag';
    tag.textContent = sourceFileName(page.path);
    item.appendChild(tag);

    const canvas = document.createElement('canvas');
    canvas.className = 'page-thumbnail';
    item.appendChild(canvas);

    const number = document.createElement('div');
    number.className = 'page-number';
    number.textContent = `p.${index + 1}`;
    item.appendChild(number);

    item.addEventListener('click', (event) => selectPage(index, event));

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
    undoButton.disabled = !data.can_undo;

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
    pages.forEach((page, index) => {
      pageList.appendChild(buildPageItem(page, index));
      post({ type: 'render_page', page_index: index, width: THUMBNAIL_WIDTH });
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
    post({ type: 'render_page', page_index: primaryIndex, width: PREVIEW_WIDTH });
  }

  openButton.addEventListener('click', () => {
    if (!hasBridge()) {
      setStatus('WebView2ブリッジ未接続（ブラウザプレビュー）');
      return;
    }
    setStatus('PDFバックエンドへ接続中…');
    post({ type: 'open_pdf' });
  });

  rotateRightButton.addEventListener('click', () => {
    if (selectedIndices.size === 0) return;
    post({ type: 'rotate_pages', indices: selectedIndicesSorted(), degrees: 90 });
  });
  rotateLeftButton.addEventListener('click', () => {
    if (selectedIndices.size === 0) return;
    post({ type: 'rotate_pages', indices: selectedIndicesSorted(), degrees: -90 });
  });
  rotate180Button.addEventListener('click', () => {
    if (selectedIndices.size === 0) return;
    post({ type: 'rotate_pages', indices: selectedIndicesSorted(), degrees: 180 });
  });
  deleteButton.addEventListener('click', () => {
    if (selectedIndices.size === 0) return;
    post({ type: 'delete_pages', indices: selectedIndicesSorted() });
  });
  undoButton.addEventListener('click', () => post({ type: 'undo_edit' }));
  exportButton.addEventListener('click', () => post({ type: 'export_images', indices: [], dpi: 150 }));
  saveButton.addEventListener('click', () => post({ type: 'save_pdf' }));

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

      if (data.type === 'page_rendered') {
        if (data.width === PREVIEW_WIDTH) {
          let img = previewEl.querySelector('img');
          if (!img) {
            previewEl.replaceChildren();
            img = document.createElement('img');
            previewEl.appendChild(img);
          }
          paintImage(img, data);
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
