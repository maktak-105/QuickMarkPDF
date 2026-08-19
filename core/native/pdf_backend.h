#pragma once

#include <cstddef>
#include <stdexcept>
#include <string>
#include <unordered_map>

namespace quickmarkpdf {

class WorkingDocument;

struct PdfDocumentInfo {
    std::string path;
    std::size_t page_count = 0;
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
};

}  // namespace quickmarkpdf
