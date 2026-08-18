#include "engine.h"
#include "pdf_backend.h"

#include <cassert>
#include <cstdio>
#include <fstream>
#include <stdexcept>

using quickmarkpdf::PageRef;
using quickmarkpdf::WorkingDocument;

namespace {
void test_append_and_rotation_normalization() {
    WorkingDocument document;
    document.append_page({"sample.pdf", 0, -90});
    assert(document.page_count() == 1);
    assert(document.page(0).rotation == 270);

    document.rotate(0, 180);
    assert(document.page(0).rotation == 90);
}

void test_reorder_and_erase() {
    WorkingDocument document;
    document.append_page({"a.pdf", 0, 0});
    document.append_page({"a.pdf", 1, 0});
    document.append_page({"b.pdf", 0, 0});

    document.reorder({2, 0, 1});
    assert(document.page(0).source_path == "b.pdf");
    document.erase({1, 1});
    assert(document.page_count() == 2);
    assert(document.page(1).source_page == 1);
}

void test_invalid_operations_are_rejected() {
    WorkingDocument document;
    document.append_page({"sample.pdf", 0, 0});

    bool invalid_rotation = false;
    try {
        document.rotate(0, 45);
    } catch (const std::invalid_argument&) {
        invalid_rotation = true;
    }
    assert(invalid_rotation);

    bool invalid_order = false;
    try {
        document.reorder({0, 0});
    } catch (const std::invalid_argument&) {
        invalid_order = true;
    }
    assert(invalid_order);

    bool invalid_erase = false;
    try {
        document.erase({1});
    } catch (const std::out_of_range&) {
        invalid_erase = true;
    }
    assert(invalid_erase);
}

void test_pdf_inspection_boundary() {
    const auto path = std::string("quickmarkpdf_test_pages.pdf");
    std::ofstream output(path, std::ios::binary);
    output << "%PDF-1.7\n"
           << "1 0 obj << /Type /Page >> endobj\n"
           << "2 0 obj << /Type /Pages /Kids [1 0 R 3 0 R] >> endobj\n"
           << "3 0 obj << /Type /Page >> endobj\n"
           << "%%EOF\n";
    output.close();
    const auto info = quickmarkpdf::PdfBackend::inspect(path);
    assert(info.page_count == 2);
    std::remove(path.c_str());
}
}  // namespace

int main() {
    test_append_and_rotation_normalization();
    test_reorder_and_erase();
    test_invalid_operations_are_rejected();
    test_pdf_inspection_boundary();
    return 0;
}
