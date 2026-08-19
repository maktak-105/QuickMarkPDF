#include "engine.h"

#include <algorithm>
#include <cstdio>
#include <filesystem>
#include <stdexcept>
#include <unordered_set>
#include <utility>

#include "image_io.h"
#include "pdf_backend.h"

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

void WorkingDocument::clear_undo_history() noexcept {
    undo_stack_.clear();
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

void WorkingDocument::rotate_many(const std::vector<std::size_t>& indices, int degrees) {
    // Validate everything before mutating anything, so a bad index or a
    // non-multiple-of-90 rotation leaves the document (and undo history)
    // untouched -- same all-or-nothing contract rotate()/reorder() have.
    std::vector<int> new_rotations;
    new_rotations.reserve(indices.size());
    for (const auto index : indices) {
        new_rotations.push_back(normalize_rotation(pages_.at(index).rotation + degrees));
    }
    if (indices.empty()) return;
    push_undo_snapshot();
    for (std::size_t i = 0; i < indices.size(); ++i) {
        pages_[indices[i]].rotation = new_rotations[i];
    }
    dirty_ = true;
}

void WorkingDocument::rebase_all_pages_to(const std::string& new_source_path) {
    for (std::size_t i = 0; i < pages_.size(); ++i) {
        pages_[i].source_path = new_source_path;
        pages_[i].source_page = i;
    }
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

namespace {
std::string to_absolute(const std::string& raw_path) {
    try {
        return std::filesystem::absolute(std::filesystem::u8path(raw_path)).u8string();
    } catch (const std::exception&) {
        return raw_path;
    }
}
}  // namespace

PdfManager::LoadResult PdfManager::load_pdfs(const std::vector<std::string>& paths,
                                              const std::unordered_map<std::string, std::string>& passwords) {
    LoadResult result;

    std::unordered_set<std::string> already_open;
    for (std::size_t i = 0; i < document_.page_count(); ++i) {
        already_open.insert(document_.page(i).source_path);
    }

    for (const auto& raw_path : paths) {
        const std::string absolute = to_absolute(raw_path);

        if (already_open.count(absolute) != 0) {
            result.duplicate_files.push_back(absolute);
            continue;
        }

        std::string password;
        if (auto it = passwords.find(raw_path); it != passwords.end()) {
            password = it->second;
        } else if (auto it2 = passwords.find(absolute); it2 != passwords.end()) {
            password = it2->second;
        }

        try {
            const PdfDocumentInfo info = PdfBackend::inspect(absolute, password);
            for (std::size_t p = 0; p < info.page_count; ++p) {
                const int rotation = p < info.page_rotations.size() ? info.page_rotations[p] : 0;
                document_.append_page(PageRef{absolute, p, rotation});
            }
            if (!password.empty()) known_passwords_[absolute] = password;
            already_open.insert(absolute);
            result.loaded_count += 1;
        } catch (const PdfPasswordRequiredError&) {
            result.password_required.push_back(absolute);
        } catch (const std::exception&) {
            // Unreadable/corrupt file: silently skipped, matching the
            // Python baseline (not counted as loaded, password-required, or
            // duplicate -- just absent from the result).
        }
    }
    return result;
}

std::size_t PdfManager::get_page_count() const noexcept {
    return document_.page_count();
}

std::vector<PdfManager::PageInfo> PdfManager::page_infos() const {
    std::vector<PageInfo> result;
    result.reserve(document_.page_count());
    for (std::size_t i = 0; i < document_.page_count(); ++i) {
        const auto& ref = document_.page(i);
        result.push_back(PageInfo{ref.source_path, ref.source_page, ref.rotation});
    }
    return result;
}

void PdfManager::reorder_pages(const std::vector<std::size_t>& order) {
    document_.reorder(order);
}

void PdfManager::rotate_page(std::size_t index, int degrees) {
    document_.rotate(index, degrees);
}

void PdfManager::rotate_pages(const std::vector<std::size_t>& indices, int degrees) {
    document_.rotate_many(indices, degrees);
}

void PdfManager::delete_pages(std::vector<std::size_t> indices) {
    std::vector<std::size_t> valid;
    valid.reserve(indices.size());
    for (const auto index : indices) {
        if (index < document_.page_count()) valid.push_back(index);
    }
    if (valid.empty()) return;
    document_.erase(valid);
}

bool PdfManager::can_undo() const noexcept {
    return document_.can_undo();
}

bool PdfManager::undo() {
    return document_.undo();
}

void PdfManager::clear_undo_history() noexcept {
    document_.clear_undo_history();
}

bool PdfManager::can_overwrite_source() const {
    if (document_.page_count() == 0) return false;
    const auto& first_path = document_.page(0).source_path;
    for (std::size_t i = 1; i < document_.page_count(); ++i) {
        if (document_.page(i).source_path != first_path) return false;
    }
    return true;
}

bool PdfManager::overwrite_source(const std::unordered_map<std::string, std::string>& passwords) {
    if (!can_overwrite_source()) return false;
    const std::string path = document_.page(0).source_path;

    std::unordered_map<std::string, std::string> merged = known_passwords_;
    for (const auto& [key, value] : passwords) merged[key] = value;

    namespace fs = std::filesystem;
    const fs::path target = fs::u8path(path);
    fs::path temp = target;
    temp += ".tmp_quickmarkpdf";

    try {
        PdfBackend::save(document_, temp.u8string(), merged);
    } catch (const std::exception&) {
        std::error_code ec;
        fs::remove(temp, ec);
        return false;
    }

    std::error_code rename_ec;
    fs::rename(temp, target, rename_ec);
    if (rename_ec) {
        std::error_code copy_ec;
        fs::copy_file(temp, target, fs::copy_options::overwrite_existing, copy_ec);
        std::error_code remove_ec;
        fs::remove(temp, remove_ec);
        if (copy_ec) return false;
    }

    document_.rebase_all_pages_to(path);
    document_.mark_saved();
    return true;
}

bool PdfManager::save_as(const std::string& output_path,
                          const std::unordered_map<std::string, std::string>& passwords) {
    std::unordered_map<std::string, std::string> merged = known_passwords_;
    for (const auto& [key, value] : passwords) merged[key] = value;

    try {
        PdfBackend::save(document_, output_path, merged);
    } catch (const std::exception&) {
        return false;
    }
    document_.mark_saved();
    return true;
}

PdfManager::ExportResult PdfManager::export_pages_to_images(
    const std::vector<std::size_t>& indices, const std::string& output_dir, const std::string& fmt, int dpi,
    const std::string& prefix, const std::optional<std::array<double, 4>>& clip) {
    ExportResult result;

    std::vector<std::size_t> targets = indices;
    if (targets.empty()) {
        targets.resize(document_.page_count());
        for (std::size_t i = 0; i < targets.size(); ++i) targets[i] = i;
    }

    namespace fs = std::filesystem;
    std::error_code mkdir_ec;
    fs::create_directories(fs::u8path(output_dir), mkdir_ec);

    std::optional<PdfBackend::ClipRectPt> backend_clip;
    if (clip) backend_clip = PdfBackend::ClipRectPt{(*clip)[0], (*clip)[1], (*clip)[2], (*clip)[3]};

    int counter = 0;
    for (const auto index : targets) {
        result.attempted += 1;
        counter += 1;

        if (index >= document_.page_count()) {
            result.errors.push_back("page index out of range: " + std::to_string(index));
            continue;
        }
        if (fmt != "png") {
            result.errors.push_back("unsupported export format (only png is implemented): " + fmt);
            continue;
        }

        const auto& ref = document_.page(index);
        try {
            std::string password;
            if (auto it = known_passwords_.find(ref.source_path); it != known_passwords_.end()) {
                password = it->second;
            }

            const RenderedPage rendered = PdfBackend::render_page_at_dpi(
                ref.source_path, ref.source_page, dpi, ref.rotation, password, backend_clip);

            char suffix[16];
            std::snprintf(suffix, sizeof(suffix), "_%04d", counter);
            const fs::path out_file = fs::u8path(output_dir) / fs::u8path(prefix + suffix + ".png");
            write_png_rgb(out_file.u8string(), rendered.width, rendered.height, rendered.rgba);
            result.success += 1;
        } catch (const std::exception& e) {
            result.errors.push_back("page " + std::to_string(index) + ": " + e.what());
        }
    }
    return result;
}

bool PdfManager::close_document(const std::string& path) {
    const std::string absolute = to_absolute(path);

    std::vector<std::size_t> to_remove;
    for (std::size_t i = 0; i < document_.page_count(); ++i) {
        if (document_.page(i).source_path == absolute) to_remove.push_back(i);
    }
    if (to_remove.empty()) return false;
    document_.erase(to_remove);
    return true;
}

void PdfManager::close_all() noexcept {
    document_.clear();
    known_passwords_.clear();
}

}  // namespace quickmarkpdf
