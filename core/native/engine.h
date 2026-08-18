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

private:
    std::vector<PageRef> pages_;
};

}  // namespace quickmarkpdf
