#pragma once

#include <array>
#include <cstddef>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

namespace quickmarkpdf {

struct PageRef {
    std::string source_path;
    std::size_t source_page = 0;
    int rotation = 0;
};

class WorkingDocument {
public:
    std::size_t page_count() const noexcept;
    const PageRef& page(std::size_t index) const;

    void append_page(PageRef page);
    void reorder(const std::vector<std::size_t>& order);
    void rotate(std::size_t index, int degrees);
    // Rotates every page in `indices` by `degrees` as a single undo step
    // (unlike calling rotate() in a loop, which would push one snapshot per
    // page) -- matches the Python baseline's multi-select rotate. Validates
    // every index and the rotation up front, so a rejected call leaves the
    // document and undo history untouched (same all-or-nothing contract as
    // the other mutators).
    void rotate_many(const std::vector<std::size_t>& indices, int degrees);
    void erase(const std::vector<std::size_t>& indices);
    void clear() noexcept;

    // Internal bookkeeping only -- NOT a user-visible edit, so it does not
    // push an undo snapshot and does not affect the dirty flag. Called right
    // after PdfBackend::save() successfully overwrites `new_source_path`
    // with the document's current pages (in their current order): every
    // page's source_page must be renumbered to its position in that freshly
    // written file (0, 1, 2, ...), since the old source_page values pointed
    // into whatever file layout existed before the overwrite. Every current
    // page must already share the same source_path (PdfManager enforces
    // this via can_overwrite_source() before calling), since the new file
    // only contains this document's pages.
    void rebase_all_pages_to(const std::string& new_source_path);

    // True once any mutating call above has run since construction, the
    // last mark_saved(), or the last clear(). Callers should invoke
    // mark_saved() only right after a PdfBackend::save() call actually
    // succeeds -- never from a catch block -- so a failed save leaves the
    // document dirty.
    bool is_dirty() const noexcept;
    void mark_saved() noexcept;

    // Each mutating call above except clear() is one undo step (a snapshot
    // is taken right before the mutation commits, so a call that ends up
    // throwing never pollutes the undo history). clear() is not itself
    // undoable and drops the whole undo history, since a reference to a
    // pre-clear PageRef is meaningless once the document has been reset --
    // mirroring the Python baseline's close_all().
    bool can_undo() const noexcept;
    bool undo();

    // Drops the undo history only -- pages_ and dirty_ are untouched. Used
    // after an "open more files" action, which the Python baseline treats
    // as not meaningfully undoable with the lightweight snapshot mechanism
    // (a fresh open starts a new undo history rather than chaining onto
    // whatever was open before).
    void clear_undo_history() noexcept;

private:
    void push_undo_snapshot();

    std::vector<PageRef> pages_;
    std::vector<std::vector<PageRef>> undo_stack_;
    bool dirty_ = false;

    static constexpr std::size_t kUndoCap = 20;
};

// Orchestrates WorkingDocument + PdfBackend into the same operation-level
// API the Python baseline's PDFManager exposes to the UI layer (open
// multiple files with dedup/password tracking, reorder/rotate/delete,
// undo, save-as/overwrite, image export, close one source file). Behavior
// is matched to python/src/pdf_editor/pdf/pdf_manager.py; the in-memory
// architecture differs (this keeps lightweight per-page source references
// and always re-imports from source files at save time, rather than PyMuPDF's
// single mutated working document), which structurally avoids a couple of
// bug classes the Python version's test suite documents as having hit
// (stale Page wrappers after a second load call; rotation not restored by
// undo because Page objects are mutated in place).
class PdfManager {
public:
    struct LoadResult {
        int loaded_count = 0;
        std::vector<std::string> password_required;  // absolute paths, in the order encountered
        std::vector<std::string> duplicate_files;     // absolute paths already open, skipped
    };

    struct PageInfo {
        std::string source_path;
        std::size_t original_page_index = 0;
        int rotation = 0;
    };

    struct ExportResult {
        int success = 0;
        int attempted = 0;
        std::vector<std::string> errors;
    };

    // Opens each path in `paths` (relative paths are resolved to absolute
    // via std::filesystem::absolute so the same file referenced two
    // different ways is still recognized as a duplicate) and appends its
    // pages, in order, to the end of the current document. A path already
    // open (from an earlier call, or repeated within this same call) is
    // skipped and reported in `duplicate_files` rather than loaded twice.
    // A path whose PdfBackend::inspect() throws PdfPasswordRequiredError is
    // reported in `password_required` and not loaded; retry it in a later
    // call with an entry in `passwords`.
    LoadResult load_pdfs(const std::vector<std::string>& paths,
                          const std::unordered_map<std::string, std::string>& passwords = {});

    std::size_t get_page_count() const noexcept;
    std::vector<PageInfo> page_infos() const;

    void reorder_pages(const std::vector<std::size_t>& order);
    void rotate_page(std::size_t index, int degrees);
    void rotate_pages(const std::vector<std::size_t>& indices, int degrees);
    void delete_pages(std::vector<std::size_t> indices);

    bool can_undo() const noexcept;
    bool undo();
    void clear_undo_history() noexcept;

    // True iff at least one page is loaded and every loaded page shares the
    // same single source file -- the only case where "overwrite the file I
    // opened" is unambiguous.
    bool can_overwrite_source() const;
    bool overwrite_source(const std::unordered_map<std::string, std::string>& passwords = {});
    bool save_as(const std::string& output_path,
                 const std::unordered_map<std::string, std::string>& passwords = {});

    // Renders each page in `indices` (or every page, if `indices` is empty)
    // to a PNG in `output_dir`, named "{prefix}_{0001-based index}.png".
    // `clip`, if set, is a crop rectangle in PDF points (page-space, before
    // DPI scaling) applied to every exported page. Only "png" is currently
    // implemented; any other `fmt` is reported per-page in `errors` rather
    // than throwing, so a partial export still returns whatever succeeded
    // (matching the Python baseline's per-page error accumulation).
    ExportResult export_pages_to_images(const std::vector<std::size_t>& indices, const std::string& output_dir,
                                         const std::string& fmt, int dpi, const std::string& prefix,
                                         const std::optional<std::array<double, 4>>& clip = std::nullopt);

    // Removes every page whose source is `path` (compared via
    // std::filesystem::absolute, matching load_pdfs's dedup comparison), as
    // one undo step. Returns false if no page had that source.
    bool close_document(const std::string& path);
    void close_all() noexcept;

private:
    WorkingDocument document_;
    // Absolute source path -> password last used to open it successfully,
    // so overwrite_source/save_as can re-open encrypted sources without
    // asking again within the same session.
    std::unordered_map<std::string, std::string> known_passwords_;
};

}  // namespace quickmarkpdf
