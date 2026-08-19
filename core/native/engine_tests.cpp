#include "engine.h"
#include "pdf_backend.h"

#include <array>
#include <cassert>
#include <cstdio>
#include <cstdint>
#include <fstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

using quickmarkpdf::PageRef;
using quickmarkpdf::WorkingDocument;

namespace {

// Writes a structurally valid minimal PDF (catalog + pages tree + xref
// table with byte-exact offsets), since pdfium needs one to parse the file
// at all -- unlike the text-scanning placeholder PdfBackend used to have.
void write_min_pdf(const std::string& path, int num_pages) {
    std::string buf = "%PDF-1.7\n";
    std::vector<std::size_t> offsets(static_cast<std::size_t>(num_pages) + 3, 0);

    auto append_obj = [&](int num, const std::string& body) {
        offsets[static_cast<std::size_t>(num)] = buf.size();
        buf += std::to_string(num) + " 0 obj\n" + body + "\nendobj\n";
    };

    append_obj(1, "<< /Type /Catalog /Pages 2 0 R >>");

    std::string kids = "[";
    for (int i = 0; i < num_pages; ++i) {
        if (i > 0) kids += " ";
        kids += std::to_string(3 + i) + " 0 R";
    }
    kids += "]";
    append_obj(2, "<< /Type /Pages /Kids " + kids + " /Count " + std::to_string(num_pages) + " >>");

    for (int i = 0; i < num_pages; ++i) {
        append_obj(3 + i, "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>");
    }

    const auto xref_offset = buf.size();
    const int total_objects = num_pages + 3;  // object numbers 0..(2+num_pages)
    buf += "xref\n0 " + std::to_string(total_objects) + "\n0000000000 65535 f \n";
    for (int n = 1; n < total_objects; ++n) {
        char entry[32];
        std::snprintf(entry, sizeof(entry), "%010zu 00000 n \n", offsets[static_cast<std::size_t>(n)]);
        buf += entry;
    }
    buf += "trailer\n<< /Size " + std::to_string(total_objects) + " /Root 1 0 R >>\n";
    buf += "startxref\n" + std::to_string(xref_offset) + "\n%%EOF\n";

    std::ofstream out(path, std::ios::binary);
    out << buf;
}
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
    write_min_pdf(path, 2);
    const auto info = quickmarkpdf::PdfBackend::inspect(path);
    assert(info.page_count == 2);
    std::remove(path.c_str());
}

void test_save_merges_reorders_and_rotates_pages() {
    const auto a_path = std::string("quickmarkpdf_test_a.pdf");
    const auto b_path = std::string("quickmarkpdf_test_b.pdf");
    const auto out_path = std::string("quickmarkpdf_test_output.pdf");
    write_min_pdf(a_path, 2);
    write_min_pdf(b_path, 1);

    WorkingDocument document;
    document.append_page({a_path, 0, 0});
    document.append_page({b_path, 0, 0});  // page from a different source file, in the middle
    document.append_page({a_path, 1, 0});
    document.rotate(1, 90);  // rotate only the page drawn from b.pdf

    quickmarkpdf::PdfBackend::save(document, out_path);

    const auto info = quickmarkpdf::PdfBackend::inspect(out_path);
    assert(info.page_count == 3);

    std::ifstream saved(out_path, std::ios::binary);
    const std::string bytes((std::istreambuf_iterator<char>(saved)), std::istreambuf_iterator<char>());
    assert(bytes.find("/Rotate 90") != std::string::npos);

    std::remove(a_path.c_str());
    std::remove(b_path.c_str());
    std::remove(out_path.c_str());
}

void test_save_reports_missing_source_file() {
    WorkingDocument document;
    document.append_page({"quickmarkpdf_missing_source.pdf", 0, 0});
    const auto out_path = std::string("quickmarkpdf_test_should_not_exist.pdf");

    bool threw = false;
    try {
        quickmarkpdf::PdfBackend::save(document, out_path);
    } catch (const std::runtime_error&) {
        threw = true;
    }
    assert(threw);
    std::remove(out_path.c_str());
}

void test_render_page_produces_blank_white_bitmap() {
    // write_min_pdf's pages are a 200x200pt MediaBox with no content stream,
    // so a blank render should come back as an opaque white square scaled
    // to the requested width.
    const auto path = std::string("quickmarkpdf_test_render.pdf");
    write_min_pdf(path, 1);

    const auto page = quickmarkpdf::PdfBackend::render_page(path, 0, 100);
    assert(page.width == 100);
    assert(page.height == 100);
    assert(page.rgba.size() == static_cast<std::size_t>(100 * 100 * 4));

    const auto pixel_at = [&](int x, int y) {
        const auto offset = (static_cast<std::size_t>(y) * 100 + static_cast<std::size_t>(x)) * 4;
        return std::array<unsigned char, 4>{page.rgba[offset], page.rgba[offset + 1], page.rgba[offset + 2],
                                             page.rgba[offset + 3]};
    };
    for (const auto& [x, y] : std::vector<std::pair<int, int>>{{0, 0}, {99, 0}, {0, 99}, {50, 50}}) {
        const auto pixel = pixel_at(x, y);
        assert(pixel[0] == 255 && pixel[1] == 255 && pixel[2] == 255 && pixel[3] == 255);
    }

    std::remove(path.c_str());
}
}  // namespace

int main() {
    test_append_and_rotation_normalization();
    test_reorder_and_erase();
    test_invalid_operations_are_rejected();
    test_pdf_inspection_boundary();
    test_save_merges_reorders_and_rotates_pages();
    test_save_reports_missing_source_file();
    test_render_page_produces_blank_white_bitmap();
    return 0;
}
