(() => {
  const status = document.querySelector('#status');
  const openButton = document.querySelector('#open-button');
  const saveButton = document.querySelector('#save-button');
  const pageList = document.querySelector('#page-list');

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
          item.textContent = `ページ ${page + 1}`;
          pageList.appendChild(item);
        }
      }
    });
  }
})();
