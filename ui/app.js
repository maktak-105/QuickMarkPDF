(() => {
  const status = document.querySelector('#status');
  const openButton = document.querySelector('#open-button');
  const saveButton = document.querySelector('#save-button');

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
    });
  }
})();
