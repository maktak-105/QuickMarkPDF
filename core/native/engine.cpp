#include "engine.h"

#include <algorithm>
#include <stdexcept>
#include <utility>

namespace quickmarkpdf {

namespace {
int normalize_rotation(int degrees) {
    int value = degrees % 360;
    if (value < 0) value += 360;
    if (value % 90 != 0) {
        throw std::invalid_argument("rotation must be a multiple of 90 degrees");
    }
    return value;
}
}  // namespace

std::size_t WorkingDocument::page_count() const noexcept {
    return pages_.size();
}

const PageRef& WorkingDocument::page(std::size_t index) const {
    return pages_.at(index);
}

bool WorkingDocument::is_dirty() const noexcept {
    return dirty_;
}

void WorkingDocument::mark_saved() noexcept {
    dirty_ = false;
}

bool WorkingDocument::can_undo() const noexcept {
    return !undo_stack_.empty();
}

void WorkingDocument::push_undo_snapshot() {
    undo_stack_.push_back(pages_);
    if (undo_stack_.size() > kUndoCap) {
        undo_stack_.erase(undo_stack_.begin());
    }
}

bool WorkingDocument::undo() {
    if (undo_stack_.empty()) return false;
    pages_ = std::move(undo_stack_.back());
    undo_stack_.pop_back();
    dirty_ = true;
    return true;
}

void WorkingDocument::append_page(PageRef page) {
    page.rotation = normalize_rotation(page.rotation);
    push_undo_snapshot();
    pages_.push_back(std::move(page));
    dirty_ = true;
}

void WorkingDocument::reorder(const std::vector<std::size_t>& order) {
    if (order.size() != pages_.size()) {
        throw std::invalid_argument("reorder must contain every page exactly once");
    }
    std::vector<bool> seen(pages_.size(), false);
    std::vector<PageRef> reordered;
    reordered.reserve(pages_.size());
    for (const auto index : order) {
        if (index >= pages_.size() || seen[index]) {
            throw std::invalid_argument("reorder contains an invalid or duplicate index");
        }
        seen[index] = true;
        reordered.push_back(pages_[index]);
    }
    push_undo_snapshot();
    pages_ = std::move(reordered);
    dirty_ = true;
}

void WorkingDocument::rotate(std::size_t index, int degrees) {
    auto& item = pages_.at(index);
    const auto new_rotation = normalize_rotation(item.rotation + degrees);
    push_undo_snapshot();
    item.rotation = new_rotation;
    dirty_ = true;
}

void WorkingDocument::erase(const std::vector<std::size_t>& indices) {
    std::vector<bool> remove(pages_.size(), false);
    for (const auto index : indices) {
        if (index >= pages_.size()) {
            throw std::out_of_range("erase index is outside the document");
        }
        remove[index] = true;
    }
    const auto removed_count = static_cast<std::size_t>(
        std::count(remove.begin(), remove.end(), true));
    push_undo_snapshot();
    std::vector<PageRef> kept;
    kept.reserve(pages_.size() - removed_count);
    for (std::size_t i = 0; i < pages_.size(); ++i) {
        if (!remove[i]) kept.push_back(std::move(pages_[i]));
    }
    pages_ = std::move(kept);
    dirty_ = true;
}

void WorkingDocument::clear() noexcept {
    pages_.clear();
    undo_stack_.clear();
    dirty_ = false;
}

}  // namespace quickmarkpdf
