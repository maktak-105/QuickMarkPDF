(() => {
  const status = document.querySelector('#status');
  const openButton = document.querySelector('#open-button');
  const saveButton = document.querySelector('#save-button');
  const pageList = document.querySelector('#page-list');
  const THUMBNAIL_WIDTH = 160;

  openButton.addEventListener('click', () => {
    status.textContent = 'PDFバックエンドへ接続中…';
    if (window.chrome?.webview) {
      window.chrome.webview.postMessage(JSON.stringify({ type: 'open_pdf' }));
    } else {
      status.textContent = 'WebView2ブリッジ未接続（ブラウザプレビュー）';
    }
  });

  saveButton.addEventListener('click', () => {
    if (window.chrome?.webview) {
      window.chrome.webview.postMessage(JSON.stringify({ type: 'save_pdf' }));
    }
  });

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

  if (window.chrome?.webview) {
    window.chrome.webview.addEventListener('message', (event) => {
      if (event.data?.type === 'backend_status') {
        status.textContent = event.data.message;
      }
      if (event.data?.type === 'pdf_opened') {
        status.textContent = `${event.data.page_count}ページを読み込みました`;
        saveButton.disabled = false;
        pageList.className = 'page-items';
        pageList.replaceChildren();
        for (let page = 0; page < event.data.page_count; page += 1) {
          const item = document.createElement('div');
          item.className = 'page-item';

          const canvas = document.createElement('canvas');
          canvas.className = 'page-thumbnail';
          canvas.dataset.pageIndex = String(page);
          item.appendChild(canvas);

          const label = document.createElement('span');
          label.textContent = `ページ ${page + 1}`;
          item.appendChild(label);

          pageList.appendChild(item);
          window.chrome.webview.postMessage(
            JSON.stringify({ type: 'render_page', page_index: page, width: THUMBNAIL_WIDTH }));
        }
      }
      if (event.data?.type === 'page_rendered') {
        const canvas = pageList.querySelector(
          `canvas[data-page-index="${event.data.page_index}"]`);
        if (canvas) paintThumbnail(canvas, event.data);
      }
    });
  }
})();
