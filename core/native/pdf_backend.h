#pragma once

#include <cstddef>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

namespace quickmarkpdf {

class WorkingDocument;

struct PdfDocumentInfo {
    std::string path;
    std::size_t page_count = 0;
};

// A page rasterized to top-left-origin, row-major RGBA8 pixels (no stride
// padding: each row is exactly width * 4 bytes), ready to hand to an HTML
// canvas via ImageData.
struct RenderedPage {
    int width = 0;
    int height = 0;
    std::vector<unsigned char> rgba;
};

// Thrown by PdfBackend::inspect / PdfBackend::save when a source PDF is
// encrypted and no password (or an incorrect one) was supplied for it.
class PdfPasswordRequiredError : public std::runtime_error {
public:
    explicit PdfPasswordRequiredError(const std::string& path);

    const std::string& path() const noexcept { return path_; }

private:
    std::string path_;
};

class PdfBackend {
public:
    // Engine-neutral boundary used by the WebView2 bridge.
    static PdfDocumentInfo inspect(const std::string& path, const std::string& password = "");

    // Builds a new PDF from `document` by importing each referenced page
    // (in order, with its rotation applied) from its source file, and
    // writes the result to `output_path`. `passwords` supplies a password
    // per source path for encrypted inputs; sources with no entry are
    // opened without a password.
    static void save(const WorkingDocument& document, const std::string& output_path,
                      const std::unordered_map<std::string, std::string>& passwords = {});

    // Rasterizes one page for a thumbnail or preview. `target_width` is the
    // desired output width in pixels; the height is derived from the page's
    // own aspect ratio (post-rotation).
    static RenderedPage render_page(const std::string& path, std::size_t page_index, int target_width,
                                     const std::string& password = "");
};

}  // namespace quickmarkpdf
