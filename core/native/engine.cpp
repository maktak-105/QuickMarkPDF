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

void WorkingDocument::append_page(PageRef page) {
    page.rotation = normalize_rotation(page.rotation);
    pages_.push_back(std::move(page));
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
    pages_ = std::move(reordered);
}

void WorkingDocument::rotate(std::size_t index, int degrees) {
    auto& item = pages_.at(index);
    item.rotation = normalize_rotation(item.rotation + degrees);
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
    std::vector<PageRef> kept;
    kept.reserve(pages_.size() - removed_count);
    for (std::size_t i = 0; i < pages_.size(); ++i) {
        if (!remove[i]) kept.push_back(std::move(pages_[i]));
    }
    pages_ = std::move(kept);
}

void WorkingDocument::clear() noexcept {
    pages_.clear();
}

}  // namespace quickmarkpdf
