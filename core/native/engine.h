#pragma once

#include <cstddef>
#include <string>
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
    void erase(const std::vector<std::size_t>& indices);
    void clear() noexcept;

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

private:
    void push_undo_snapshot();

    std::vector<PageRef> pages_;
    std::vector<std::vector<PageRef>> undo_stack_;
    bool dirty_ = false;

    static constexpr std::size_t kUndoCap = 20;
};

}  // namespace quickmarkpdf
