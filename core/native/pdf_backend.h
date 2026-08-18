#pragma once

#include <cstddef>
#include <string>

namespace quickmarkpdf {

struct PdfDocumentInfo {
    std::string path;
    std::size_t page_count = 0;
};

class PdfBackend {
public:
    // Engine-neutral boundary used by the WebView2 bridge.
    static PdfDocumentInfo inspect(const std::string& path);
};

}  // namespace quickmarkpdf
