#pragma once

#include <cstddef>
#include <optional>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

namespace quickmarkpdf {

class WorkingDocument;

struct PdfDocumentInfo {
    std::string path;
    std::size_t page_count = 0;
    // Each page's own stored rotation in degrees (0/90/180/270), read via
    // FPDFPage_GetRotation. WorkingDocument's rotation contract is an
    // absolute value applied via FPDFPage_SetRotation at save/render time,
    // so a freshly appended PageRef must start from this -- not 0 -- or a
    // save/render would silently un-rotate a page the source file already
    // had rotated.
    std::vector<int> page_rotations;
};

// One line (or line-segment) of selectable text on a page, in top-left-
// origin PDF points -- the same coordinate convention RenderedPage's
// page_width_pt/page_height_pt use, so a caller can place it directly over
// a rendered bitmap without a separate axis flip.
struct TextRun {
    double x0 = 0, y0 = 0, x1 = 0, y1 = 0;
    std::string text;  // UTF-8
};

struct TextLayout {
    double page_width_pt = 0;
    double page_height_pt = 0;
    std::vector<TextRun> runs;
};

// A page rasterized to top-left-origin, row-major RGBA8 pixels (no stride
// padding: each row is exactly width * 4 bytes), ready to hand to an HTML
// canvas via ImageData.
struct RenderedPage {
    int width = 0;
    int height = 0;
    std::vector<unsigned char> rgba;
    // The page's own size in PDF points (after `rotation` is applied, so it
    // matches the orientation of width/height above) -- lets a caller that
    // only knows the rendered pixel size convert a selection rectangle back
    // to PDF points (e.g. for ClipRectPt) without a separate query.
    double page_width_pt = 0;
    double page_height_pt = 0;
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
    // own aspect ratio after `rotation` (an absolute value in degrees --
    // typically a WorkingDocument PageRef's rotation, not a delta -- 0/90/
    // 180/270) is applied, so a 90/270 rotation swaps the output's aspect
    // ratio the same way PdfBackend::save's output page would.
    static RenderedPage render_page(const std::string& path, std::size_t page_index, int target_width,
                                     int rotation, const std::string& password = "");

    // A crop rectangle in PDF points (page-space, before DPI scaling and
    // before `rotation` is applied), e.g. {x0,y0,x1,y1} = {10,10,110,110}.
    struct ClipRectPt {
        double x0 = 0, y0 = 0, x1 = 0, y1 = 0;
    };

    // Like render_page, but sized from a target resolution in DPI (pixels
    // per 72pt inch) instead of an exact pixel width -- for image export,
    // where the caller thinks in DPI rather than pixels. If `clip` is set,
    // the full page is rendered and then cropped to that rectangle scaled
    // by dpi/72 -- so at 72 DPI, 1 PDF point == 1 output pixel.
    static RenderedPage render_page_at_dpi(const std::string& path, std::size_t page_index, int dpi,
                                            int rotation, const std::string& password = "",
                                            const std::optional<ClipRectPt>& clip = std::nullopt);

    // Extracts the page's selectable text as a list of line-level runs, each
    // with its bounding box in top-left-origin PDF points (see TextRun) --
    // for overlaying a transparent, selectable text layer on top of a
    // render_page bitmap. `rotation` must match the same PageRef rotation
    // passed to render_page for the two coordinate systems to line up.
    // Pages with no extractable text (scanned images, or text baked in as
    // vector paths e.g. MathJax's SVG output) yield an empty `runs` list,
    // not an error.
    static TextLayout get_text_layout(const std::string& path, std::size_t page_index, int rotation,
                                       const std::string& password = "");
};

}  // namespace quickmarkpdf
