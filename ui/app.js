(() => {
  const status = document.querySelector('#status');
  const openButton = document.querySelector('#open-button');
  const undoButton = document.querySelector('#undo-button');
  const exportButton = document.querySelector('#export-button');
  const saveButton = document.querySelector('#save-button');
  const pageList = document.querySelector('#page-list');
  const THUMBNAIL_WIDTH = 160;

  const hasBridge = () => Boolean(window.chrome?.webview);
  const post = (payload) => {
    if (hasBridge()) window.chrome.webview.postMessage(JSON.stringify(payload));
  };

  openButton.addEventListener('click', () => {
    if (!hasBridge()) {
      status.textContent = 'WebView2ブリッジ未接続（ブラウザプレビュー）';
      return;
    }
    status.textContent = 'PDFバックエンドへ接続中…';
    post({ type: 'open_pdf' });
  });

  undoButton.addEventListener('click', () => post({ type: 'undo_edit' }));
  exportButton.addEventListener('click', () => post({ type: 'export_images', indices: [] }));
  saveButton.addEventListener('click', () => post({ type: 'save_pdf' }));

  function paintThumbnail(canvas, message) {
    const binary = atob(message.pixels);
    const bytes = new Uint8ClampedArray(binary.length);
    for (let i = 0; i < binary.length; i += 1) {
      bytes[i] = binary.charCodeAt(i);
    }
    canvas.width = message.width;
    canvas.height = message.height;
    const context = canvas.getContext('2d');
    context.putImageData(new ImageData(bytes, message.width, message.height), 0, 0);
  }

  function sourceFileName(path) {
    const parts = path.split(/[\\/]/);
    return parts[parts.length - 1] || path;
  }

  function movePage(fromIndex, toIndex, pageCount) {
    if (toIndex < 0 || toIndex >= pageCount) return;
    const order = Array.from({ length: pageCount }, (_, i) => i);
    const [moved] = order.splice(fromIndex, 1);
    order.splice(toIndex, 0, moved);
    post({ type: 'reorder_pages', order });
  }

  function buildPageItem(page, index, pageCount) {
    const item = document.createElement('div');
    item.className = 'page-item';

    const canvas = document.createElement('canvas');
    canvas.className = 'page-thumbnail';
    canvas.dataset.pageIndex = String(index);
    item.appendChild(canvas);

    const label = document.createElement('span');
    label.className = 'page-label';
    label.textContent = `${sourceFileName(page.path)} #${page.source_page + 1}`;
    item.appendChild(label);

    const controls = document.createElement('div');
    controls.className = 'page-controls';

    const upButton = document.createElement('button');
    upButton.textContent = '↑';
    upButton.title = '前へ移動';
    upButton.disabled = index === 0;
    upButton.addEventListener('click', () => movePage(index, index - 1, pageCount));
    controls.appendChild(upButton);

    const downButton = document.createElement('button');
    downButton.textContent = '↓';
    downButton.title = '後ろへ移動';
    downButton.disabled = index === pageCount - 1;
    downButton.addEventListener('click', () => movePage(index, index + 1, pageCount));
    controls.appendChild(downButton);

    const rotateButton = document.createElement('button');
    rotateButton.textContent = '回転';
    rotateButton.title = '90度回転';
    rotateButton.addEventListener('click', () => {
      post({ type: 'rotate_page', page_index: index, degrees: 90 });
    });
    controls.appendChild(rotateButton);

    const deleteButton = document.createElement('button');
    deleteButton.textContent = '削除';
    deleteButton.addEventListener('click', () => {
      post({ type: 'delete_pages', indices: [index] });
    });
    controls.appendChild(deleteButton);

    item.appendChild(controls);
    return item;
  }

  function renderPageList(data) {
    undoButton.disabled = !data.can_undo;
    exportButton.disabled = data.page_count === 0;
    saveButton.disabled = data.page_count === 0;

    if (data.page_count === 0) {
      pageList.className = 'empty';
      pageList.textContent = 'PDFを開くとページ一覧を表示します。';
      return;
    }

    pageList.className = 'page-items';
    pageList.replaceChildren();
    data.pages.forEach((page, index) => {
      pageList.appendChild(buildPageItem(page, index, data.page_count));
      post({ type: 'render_page', page_index: index, width: THUMBNAIL_WIDTH });
    });
  }

  if (hasBridge()) {
    window.chrome.webview.addEventListener('message', (event) => {
      const data = event.data;
      if (!data) return;

      if (data.type === 'backend_status') {
        status.textContent = data.message;
      }

      if (data.type === 'pdf_opened') {
        if (typeof data.loaded_files === 'number') {
          let message = `${data.loaded_files}件のファイルを読み込みました（${data.page_count}ページ）`;
          if (data.failed_files && data.failed_files.length > 0) {
            message += ` / 読み込めなかったファイル: ${data.failed_files.join(', ')}`;
          }
          status.textContent = message;
        }
        renderPageList(data);
      }

      if (data.type === 'document_state') {
        renderPageList(data);
      }

      if (data.type === 'page_rendered') {
        const canvas = pageList.querySelector(`canvas[data-page-index="${data.page_index}"]`);
        if (canvas) paintThumbnail(canvas, data);
      }
    });
  }
})();
