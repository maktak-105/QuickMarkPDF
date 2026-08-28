#include "engine.h"
#include "pdf_backend.h"

#include <array>
#include <cassert>
#include <cstdio>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

using quickmarkpdf::PageRef;
using quickmarkpdf::PdfManager;
using quickmarkpdf::WorkingDocument;

namespace {

// Writes a structurally valid minimal PDF (catalog + pages tree + xref
// table with byte-exact offsets), since pdfium needs one to parse the file
// at all -- unlike the text-scanning placeholder PdfBackend used to have.
void write_min_pdf(const std::string& path, int num_pages, int page_width = 200, int page_height = 200,
                    const std::vector<int>& page_rotations = {}) {
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

    const std::string media_box =
        "[0 0 " + std::to_string(page_width) + " " + std::to_string(page_height) + "]";
    for (int i = 0; i < num_pages; ++i) {
        const std::string rotate_entry = static_cast<std::size_t>(i) < page_rotations.size()
            ? " /Rotate " + std::to_string(page_rotations[static_cast<std::size_t>(i)])
            : "";
        append_obj(3 + i, "<< /Type /Page /Parent 2 0 R /MediaBox " + media_box + rotate_entry + " >>");
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

// Like write_min_pdf, but the single page also carries a content stream
// drawing `text` with the standard Helvetica font (no embedded font file
// needed -- pdfium resolves the 14 standard PDF fonts by name) at
// (text_x, text_y) in PDF points, for exercising
// PdfBackend::get_text_layout. rotation is the page's own /Rotate entry
// (0/90/180/270), matching write_min_pdf's page_rotations parameter for a
// single page.
void write_text_pdf(const std::string& path, const std::string& text, int text_x, int text_y,
                     int page_width = 200, int page_height = 200, int rotation = 0) {
    std::string buf = "%PDF-1.7\n";
    std::vector<std::size_t> offsets(6, 0);

    auto append_obj = [&](int num, const std::string& body) {
        offsets[static_cast<std::size_t>(num)] = buf.size();
        buf += std::to_string(num) + " 0 obj\n" + body + "\nendobj\n";
    };

    append_obj(1, "<< /Type /Catalog /Pages 2 0 R >>");
    append_obj(2, "<< /Type /Pages /Kids [3 0 R] /Count 1 >>");
    const std::string media_box =
        "[0 0 " + std::to_string(page_width) + " " + std::to_string(page_height) + "]";
    const std::string rotate_entry = rotation != 0 ? " /Rotate " + std::to_string(rotation) : "";
    append_obj(3, "<< /Type /Page /Parent 2 0 R /MediaBox " + media_box + rotate_entry +
                      " /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>");

    const std::string content =
        "BT /F1 24 Tf " + std::to_string(text_x) + " " + std::to_string(text_y) + " Td (" + text + ") Tj ET";
    append_obj(4, "<< /Length " + std::to_string(content.size()) + " >>\nstream\n" + content + "\nendstream");
    append_obj(5, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>");

    const auto xref_offset = buf.size();
    buf += "xref\n0 6\n0000000000 65535 f \n";
    for (int n = 1; n < 6; ++n) {
        char entry[32];
        std::snprintf(entry, sizeof(entry), "%010zu 00000 n \n", offsets[static_cast<std::size_t>(n)]);
        buf += entry;
    }
    buf += "trailer\n<< /Size 6 /Root 1 0 R >>\n";
    buf += "startxref\n" + std::to_string(xref_offset) + "\n%%EOF\n";

    std::ofstream out(path, std::ios::binary);
    out << buf;
}

// A genuinely encrypted (AES-128, standard security handler) 2-page PDF,
// user password "secret123". Unlike write_min_pdf() above, PDF encryption's
// key derivation (per the spec's standard security handler) is too involved
// to hand-write a valid encrypted file byte-by-byte, so this is instead the
// exact output of PyMuPDF's Document.save(..., encryption=PDF_ENCRYPT_AES_128,
// user_pw="secret123", owner_pw="secret123-owner"), generated once and
// embedded here rather than checked in as a separate binary fixture file --
// matching write_min_pdf's temp-file-then-PdfBackend::inspect() pattern
// without adding a committed binary asset.
static const unsigned char kEncryptedFixturePdf[] = {
    0x25, 0x50, 0x44, 0x46, 0x2d, 0x31, 0x2e, 0x37, 0x0a, 0x25, 0xc2, 0xb5, 0xc2, 0xb6, 0x0a, 0x25,
    0x20, 0x57, 0x72, 0x69, 0x74, 0x74, 0x65, 0x6e, 0x20, 0x62, 0x79, 0x20, 0x4d, 0x75, 0x50, 0x44,
    0x46, 0x20, 0x31, 0x2e, 0x32, 0x37, 0x2e, 0x32, 0x0a, 0x0a, 0x31, 0x20, 0x30, 0x20, 0x6f, 0x62,
    0x6a, 0x0a, 0x3c, 0x3c, 0x2f, 0x54, 0x79, 0x70, 0x65, 0x2f, 0x43, 0x61, 0x74, 0x61, 0x6c, 0x6f,
    0x67, 0x2f, 0x50, 0x61, 0x67, 0x65, 0x73, 0x20, 0x32, 0x20, 0x30, 0x20, 0x52, 0x2f, 0x49, 0x6e,
    0x66, 0x6f, 0x3c, 0x3c, 0x2f, 0x50, 0x72, 0x6f, 0x64, 0x75, 0x63, 0x65, 0x72, 0x3c, 0x32, 0x41,
    0x32, 0x44, 0x39, 0x39, 0x34, 0x35, 0x44, 0x45, 0x36, 0x31, 0x38, 0x37, 0x32, 0x43, 0x34, 0x41,
    0x36, 0x30, 0x42, 0x30, 0x39, 0x32, 0x37, 0x39, 0x41, 0x42, 0x43, 0x46, 0x37, 0x33, 0x32, 0x37,
    0x45, 0x42, 0x41, 0x45, 0x36, 0x33, 0x35, 0x34, 0x37, 0x34, 0x44, 0x37, 0x31, 0x31, 0x33, 0x30,
    0x41, 0x44, 0x38, 0x35, 0x33, 0x39, 0x46, 0x41, 0x38, 0x43, 0x31, 0x34, 0x33, 0x34, 0x3e, 0x3e,
    0x3e, 0x3e, 0x3e, 0x0a, 0x65, 0x6e, 0x64, 0x6f, 0x62, 0x6a, 0x0a, 0x0a, 0x32, 0x20, 0x30, 0x20,
    0x6f, 0x62, 0x6a, 0x0a, 0x3c, 0x3c, 0x2f, 0x54, 0x79, 0x70, 0x65, 0x2f, 0x50, 0x61, 0x67, 0x65,
    0x73, 0x2f, 0x43, 0x6f, 0x75, 0x6e, 0x74, 0x20, 0x32, 0x2f, 0x4b, 0x69, 0x64, 0x73, 0x5b, 0x34,
    0x20, 0x30, 0x20, 0x52, 0x20, 0x36, 0x20, 0x30, 0x20, 0x52, 0x5d, 0x3e, 0x3e, 0x0a, 0x65, 0x6e,
    0x64, 0x6f, 0x62, 0x6a, 0x0a, 0x0a, 0x33, 0x20, 0x30, 0x20, 0x6f, 0x62, 0x6a, 0x0a, 0x3c, 0x3c,
    0x3e, 0x3e, 0x0a, 0x65, 0x6e, 0x64, 0x6f, 0x62, 0x6a, 0x0a, 0x0a, 0x34, 0x20, 0x30, 0x20, 0x6f,
    0x62, 0x6a, 0x0a, 0x3c, 0x3c, 0x2f, 0x54, 0x79, 0x70, 0x65, 0x2f, 0x50, 0x61, 0x67, 0x65, 0x2f,
    0x4d, 0x65, 0x64, 0x69, 0x61, 0x42, 0x6f, 0x78, 0x5b, 0x30, 0x20, 0x30, 0x20, 0x32, 0x30, 0x30,
    0x20, 0x32, 0x30, 0x30, 0x5d, 0x2f, 0x52, 0x6f, 0x74, 0x61, 0x74, 0x65, 0x20, 0x30, 0x2f, 0x52,
    0x65, 0x73, 0x6f, 0x75, 0x72, 0x63, 0x65, 0x73, 0x20, 0x33, 0x20, 0x30, 0x20, 0x52, 0x2f, 0x50,
    0x61, 0x72, 0x65, 0x6e, 0x74, 0x20, 0x32, 0x20, 0x30, 0x20, 0x52, 0x3e, 0x3e, 0x0a, 0x65, 0x6e,
    0x64, 0x6f, 0x62, 0x6a, 0x0a, 0x0a, 0x35, 0x20, 0x30, 0x20, 0x6f, 0x62, 0x6a, 0x0a, 0x3c, 0x3c,
    0x3e, 0x3e, 0x0a, 0x65, 0x6e, 0x64, 0x6f, 0x62, 0x6a, 0x0a, 0x0a, 0x36, 0x20, 0x30, 0x20, 0x6f,
    0x62, 0x6a, 0x0a, 0x3c, 0x3c, 0x2f, 0x54, 0x79, 0x70, 0x65, 0x2f, 0x50, 0x61, 0x67, 0x65, 0x2f,
    0x4d, 0x65, 0x64, 0x69, 0x61, 0x42, 0x6f, 0x78, 0x5b, 0x30, 0x20, 0x30, 0x20, 0x32, 0x30, 0x30,
    0x20, 0x32, 0x30, 0x30, 0x5d, 0x2f, 0x52, 0x6f, 0x74, 0x61, 0x74, 0x65, 0x20, 0x30, 0x2f, 0x52,
    0x65, 0x73, 0x6f, 0x75, 0x72, 0x63, 0x65, 0x73, 0x20, 0x35, 0x20, 0x30, 0x20, 0x52, 0x2f, 0x50,
    0x61, 0x72, 0x65, 0x6e, 0x74, 0x20, 0x32, 0x20, 0x30, 0x20, 0x52, 0x3e, 0x3e, 0x0a, 0x65, 0x6e,
    0x64, 0x6f, 0x62, 0x6a, 0x0a, 0x0a, 0x78, 0x72, 0x65, 0x66, 0x0a, 0x30, 0x20, 0x37, 0x0a, 0x30,
    0x30, 0x30, 0x30, 0x30, 0x30, 0x30, 0x30, 0x30, 0x30, 0x20, 0x36, 0x35, 0x35, 0x33, 0x35, 0x20,
    0x66, 0x20, 0x0a, 0x30, 0x30, 0x30, 0x30, 0x30, 0x30, 0x30, 0x30, 0x34, 0x32, 0x20, 0x30, 0x30,
    0x30, 0x30, 0x30, 0x20, 0x6e, 0x20, 0x0a, 0x30, 0x30, 0x30, 0x30, 0x30, 0x30, 0x30, 0x31, 0x37,
    0x32, 0x20, 0x30, 0x30, 0x30, 0x30, 0x30, 0x20, 0x6e, 0x20, 0x0a, 0x30, 0x30, 0x30, 0x30, 0x30,
    0x30, 0x30, 0x32, 0x33, 0x30, 0x20, 0x30, 0x30, 0x30, 0x30, 0x30, 0x20, 0x6e, 0x20, 0x0a, 0x30,
    0x30, 0x30, 0x30, 0x30, 0x30, 0x30, 0x32, 0x35, 0x31, 0x20, 0x30, 0x30, 0x30, 0x30, 0x30, 0x20,
    0x6e, 0x20, 0x0a, 0x30, 0x30, 0x30, 0x30, 0x30, 0x30, 0x30, 0x33, 0x34, 0x32, 0x20, 0x30, 0x30,
    0x30, 0x30, 0x30, 0x20, 0x6e, 0x20, 0x0a, 0x30, 0x30, 0x30, 0x30, 0x30, 0x30, 0x30, 0x33, 0x36,
    0x33, 0x20, 0x30, 0x30, 0x30, 0x30, 0x30, 0x20, 0x6e, 0x20, 0x0a, 0x0a, 0x74, 0x72, 0x61, 0x69,
    0x6c, 0x65, 0x72, 0x0a, 0x3c, 0x3c, 0x2f, 0x53, 0x69, 0x7a, 0x65, 0x20, 0x37, 0x2f, 0x52, 0x6f,
    0x6f, 0x74, 0x20, 0x31, 0x20, 0x30, 0x20, 0x52, 0x2f, 0x49, 0x44, 0x5b, 0x3c, 0x43, 0x32, 0x39,
    0x43, 0x43, 0x32, 0x38, 0x44, 0x31, 0x44, 0x37, 0x31, 0x36, 0x37, 0x30, 0x37, 0x32, 0x34, 0x31,
    0x37, 0x33, 0x39, 0x43, 0x32, 0x39, 0x30, 0x32, 0x41, 0x43, 0x32, 0x41, 0x43, 0x3e, 0x3c, 0x35,
    0x32, 0x36, 0x44, 0x37, 0x42, 0x31, 0x35, 0x38, 0x38, 0x45, 0x45, 0x38, 0x34, 0x30, 0x36, 0x35,
    0x39, 0x37, 0x41, 0x44, 0x44, 0x36, 0x35, 0x45, 0x39, 0x36, 0x45, 0x42, 0x35, 0x33, 0x37, 0x3e,
    0x5d, 0x2f, 0x45, 0x6e, 0x63, 0x72, 0x79, 0x70, 0x74, 0x3c, 0x3c, 0x2f, 0x46, 0x69, 0x6c, 0x74,
    0x65, 0x72, 0x2f, 0x53, 0x74, 0x61, 0x6e, 0x64, 0x61, 0x72, 0x64, 0x2f, 0x52, 0x20, 0x34, 0x2f,
    0x56, 0x20, 0x34, 0x2f, 0x4c, 0x65, 0x6e, 0x67, 0x74, 0x68, 0x20, 0x31, 0x32, 0x38, 0x2f, 0x50,
    0x20, 0x2d, 0x33, 0x38, 0x35, 0x32, 0x2f, 0x45, 0x6e, 0x63, 0x72, 0x79, 0x70, 0x74, 0x4d, 0x65,
    0x74, 0x61, 0x64, 0x61, 0x74, 0x61, 0x20, 0x74, 0x72, 0x75, 0x65, 0x2f, 0x53, 0x74, 0x6d, 0x46,
    0x2f, 0x53, 0x74, 0x64, 0x43, 0x46, 0x2f, 0x53, 0x74, 0x72, 0x46, 0x2f, 0x53, 0x74, 0x64, 0x43,
    0x46, 0x2f, 0x43, 0x46, 0x3c, 0x3c, 0x2f, 0x53, 0x74, 0x64, 0x43, 0x46, 0x3c, 0x3c, 0x2f, 0x41,
    0x75, 0x74, 0x68, 0x45, 0x76, 0x65, 0x6e, 0x74, 0x2f, 0x44, 0x6f, 0x63, 0x4f, 0x70, 0x65, 0x6e,
    0x2f, 0x43, 0x46, 0x4d, 0x2f, 0x41, 0x45, 0x53, 0x56, 0x32, 0x2f, 0x4c, 0x65, 0x6e, 0x67, 0x74,
    0x68, 0x20, 0x31, 0x36, 0x3e, 0x3e, 0x3e, 0x3e, 0x2f, 0x4f, 0x3c, 0x42, 0x39, 0x46, 0x41, 0x41,
    0x42, 0x38, 0x36, 0x38, 0x41, 0x38, 0x32, 0x45, 0x34, 0x32, 0x45, 0x34, 0x35, 0x41, 0x35, 0x34,
    0x43, 0x43, 0x38, 0x37, 0x42, 0x32, 0x36, 0x46, 0x44, 0x33, 0x32, 0x35, 0x42, 0x44, 0x44, 0x35,
    0x31, 0x36, 0x45, 0x42, 0x45, 0x45, 0x30, 0x43, 0x41, 0x46, 0x31, 0x43, 0x36, 0x30, 0x45, 0x42,
    0x34, 0x46, 0x41, 0x38, 0x38, 0x43, 0x44, 0x45, 0x32, 0x32, 0x46, 0x3e, 0x2f, 0x55, 0x3c, 0x35,
    0x39, 0x36, 0x42, 0x32, 0x36, 0x30, 0x38, 0x35, 0x36, 0x31, 0x43, 0x37, 0x34, 0x36, 0x42, 0x45,
    0x38, 0x32, 0x42, 0x33, 0x34, 0x41, 0x44, 0x41, 0x46, 0x34, 0x42, 0x36, 0x39, 0x35, 0x37, 0x32,
    0x38, 0x42, 0x46, 0x34, 0x45, 0x35, 0x45, 0x34, 0x45, 0x37, 0x35, 0x38, 0x41, 0x34, 0x31, 0x36,
    0x34, 0x30, 0x30, 0x34, 0x45, 0x35, 0x36, 0x46, 0x46, 0x46, 0x41, 0x30, 0x31, 0x30, 0x38, 0x3e,
    0x3e, 0x3e, 0x3e, 0x3e, 0x0a, 0x73, 0x74, 0x61, 0x72, 0x74, 0x78, 0x72, 0x65, 0x66, 0x0a, 0x34,
    0x35, 0x34, 0x0a, 0x25, 0x25, 0x45, 0x4f, 0x46, 0x0a,
};

void write_encrypted_fixture_pdf(const std::string& path) {
    std::ofstream out(path, std::ios::binary);
    out.write(reinterpret_cast<const char*>(kEncryptedFixturePdf),
              static_cast<std::streamsize>(sizeof(kEncryptedFixturePdf)));
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

void test_no_undo_available_initially() {
    WorkingDocument document;
    assert(!document.can_undo());
    assert(!document.undo());
}

void test_undo_reorder() {
    WorkingDocument document;
    document.append_page({"a.pdf", 0, 0});
    document.append_page({"a.pdf", 1, 0});
    document.mark_saved();

    document.reorder({1, 0});
    assert(document.page(0).source_page == 1);
    assert(document.is_dirty());

    assert(document.undo());
    assert(document.page(0).source_page == 0);
    assert(document.page(1).source_page == 1);
}

void test_undo_delete_pages() {
    WorkingDocument document;
    document.append_page({"a.pdf", 0, 0});
    document.append_page({"a.pdf", 1, 0});
    document.append_page({"a.pdf", 2, 0});

    document.erase({1});
    assert(document.page_count() == 2);

    assert(document.undo());
    assert(document.page_count() == 3);
    assert(document.page(1).source_page == 1);
}

void test_undo_rotate_restores_actual_rotation() {
    WorkingDocument document;
    document.append_page({"a.pdf", 0, 0});

    document.rotate(0, 90);
    assert(document.page(0).rotation == 90);

    assert(document.undo());
    assert(document.page(0).rotation == 0);
}

void test_invalid_rotate_does_not_create_undo_step() {
    // A rejected mutation must not pollute the undo history with a no-op
    // snapshot -- undo() should still reach further back to the last real
    // change.
    WorkingDocument document;
    document.append_page({"a.pdf", 0, 0});
    document.rotate(0, 90);
    assert(document.can_undo());

    bool rejected = false;
    try {
        document.rotate(0, 45);
    } catch (const std::invalid_argument&) {
        rejected = true;
    }
    assert(rejected);

    // Only the two real edits above (append_page, rotate) should be
    // undoable -- the rejected rotate must not have pushed a spurious
    // third snapshot.
    int steps = 0;
    while (document.undo()) ++steps;
    assert(steps == 2);
    assert(document.page_count() == 0);
}

void test_undo_stack_capped() {
    WorkingDocument document;
    document.append_page({"a.pdf", 0, 0});
    for (int i = 0; i < 25; ++i) {
        document.rotate(0, 90);
    }

    int undone = 0;
    while (document.undo()) ++undone;
    assert(undone == 20);
}

void test_clear_wipes_undo_history_and_dirty_flag() {
    WorkingDocument document;
    document.append_page({"a.pdf", 0, 0});
    document.rotate(0, 90);
    assert(document.can_undo());
    assert(document.is_dirty());

    document.clear();
    assert(!document.can_undo());
    assert(!document.undo());
    assert(!document.is_dirty());
}

void test_dirty_tracks_unsaved_changes() {
    WorkingDocument document;
    assert(!document.is_dirty());

    document.append_page({"a.pdf", 0, 0});
    assert(document.is_dirty());

    document.mark_saved();
    assert(!document.is_dirty());

    document.rotate(0, 90);
    assert(document.is_dirty());

    // Undoing back to the last-saved arrangement is still treated as a
    // change relative to what's on disk -- a real save is required again.
    assert(document.undo());
    assert(document.is_dirty());
}

void test_pdf_inspection_boundary() {
    const auto path = std::string("quickmarkpdf_test_pages.pdf");
    write_min_pdf(path, 2);
    const auto info = quickmarkpdf::PdfBackend::inspect(path);
    assert(info.page_count == 2);
    assert(info.page_rotations.size() == 2);
    assert(info.page_rotations[0] == 0);
    assert(info.page_rotations[1] == 0);
    std::remove(path.c_str());
}

void test_inspect_reports_each_pages_own_rotation() {
    // A freshly appended PageRef must seed its rotation from the source
    // page's own /Rotate, not 0 -- otherwise PdfBackend::save/render_page
    // would silently un-rotate a page the source file already had rotated,
    // since their rotation contract is absolute, not a delta.
    const auto path = std::string("quickmarkpdf_test_rotated_source.pdf");
    write_min_pdf(path, 3, 200, 200, {0, 90, 270});
    const auto info = quickmarkpdf::PdfBackend::inspect(path);
    assert(info.page_rotations.size() == 3);
    assert(info.page_rotations[0] == 0);
    assert(info.page_rotations[1] == 90);
    assert(info.page_rotations[2] == 270);
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
    saved.close();  // must close before std::remove(out_path) below -- Windows won't delete an open file
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

    const auto page = quickmarkpdf::PdfBackend::render_page(path, 0, 100, /*rotation=*/0);
    assert(page.width == 100);
    assert(page.height == 100);
    assert(page.rgba.size() == static_cast<std::size_t>(100 * 100 * 4));

    const auto pixel_at = [&](const quickmarkpdf::RenderedPage& p, int x, int y) {
        const auto offset = (static_cast<std::size_t>(y) * static_cast<std::size_t>(p.width) +
                              static_cast<std::size_t>(x)) * 4;
        return std::array<unsigned char, 4>{p.rgba[offset], p.rgba[offset + 1], p.rgba[offset + 2],
                                             p.rgba[offset + 3]};
    };
    for (const auto& [x, y] : std::vector<std::pair<int, int>>{{0, 0}, {99, 0}, {0, 99}, {50, 50}}) {
        const auto pixel = pixel_at(page, x, y);
        assert(pixel[0] == 255 && pixel[1] == 255 && pixel[2] == 255 && pixel[3] == 255);
    }

    std::remove(path.c_str());
}

void test_render_page_rotation_swaps_aspect_ratio() {
    // A 100x200pt (portrait) page rotated 90 degrees should render as
    // landscape: requesting a 100pt-wide render should come back ~50pt
    // tall (matching the rotated page's own aspect ratio), not 200pt tall.
    const auto path = std::string("quickmarkpdf_test_render_rotated.pdf");
    write_min_pdf(path, 1, /*page_width=*/100, /*page_height=*/200);

    const auto unrotated = quickmarkpdf::PdfBackend::render_page(path, 0, 100, /*rotation=*/0);
    assert(unrotated.width == 100);
    assert(unrotated.height == 200);

    const auto rotated = quickmarkpdf::PdfBackend::render_page(path, 0, 100, /*rotation=*/90);
    assert(rotated.width == 100);
    assert(rotated.height == 50);

    std::remove(path.c_str());
}

void test_render_page_at_dpi_matches_pdf_point_size() {
    // A 72x144pt page (i.e. exactly 1x2 inches) at 100 DPI should come back
    // as a 100x200px bitmap: DPI is literally pixels-per-72pt-inch.
    const auto path = std::string("quickmarkpdf_test_render_dpi.pdf");
    write_min_pdf(path, 1, /*page_width=*/72, /*page_height=*/144);

    const auto page = quickmarkpdf::PdfBackend::render_page_at_dpi(path, 0, /*dpi=*/100, /*rotation=*/0);
    assert(page.width == 100);
    assert(page.height == 200);

    std::remove(path.c_str());
}

void test_get_text_layout_extracts_text_and_bbox() {
    const auto path = std::string("quickmarkpdf_test_text_layout.pdf");
    write_text_pdf(path, "Hello", /*text_x=*/20, /*text_y=*/150, /*page_width=*/200, /*page_height=*/200);

    const auto layout = quickmarkpdf::PdfBackend::get_text_layout(path, 0, /*rotation=*/0);
    assert(layout.page_width_pt == 200.0);
    assert(layout.page_height_pt == 200.0);
    assert(!layout.runs.empty());

    bool found = false;
    for (const auto& run : layout.runs) {
        if (run.text.find("Hello") == std::string::npos) continue;
        found = true;
        // Bbox must land inside the page, in top-left-origin coordinates
        // (see get_text_layout's comment) -- the Td baseline sits at
        // y=150pt in PDF's bottom-left space, i.e. roughly 50pt from the
        // top, so the run's top-left-origin y-range should straddle that.
        assert(run.x0 >= 0 && run.x1 <= 200 && run.x0 < run.x1);
        assert(run.y0 >= 0 && run.y1 <= 200 && run.y0 < run.y1);
        assert(run.y0 < 55 && run.y1 > 40);
    }
    assert(found);

    std::remove(path.c_str());
}

void test_get_text_layout_empty_for_blank_page() {
    // write_min_pdf's pages have no content stream (see
    // test_render_page_produces_blank_white_bitmap), so there is nothing to
    // extract -- an empty run list, not an error/throw.
    const auto path = std::string("quickmarkpdf_test_text_layout_blank.pdf");
    write_min_pdf(path, 1);

    const auto layout = quickmarkpdf::PdfBackend::get_text_layout(path, 0, /*rotation=*/0);
    assert(layout.runs.empty());

    std::remove(path.c_str());
}

void test_get_text_layout_rotation_keeps_bbox_within_rotated_page() {
    // A 100x200pt (portrait) page rotated 90 degrees renders as landscape
    // (200x100pt), mirroring test_render_page_rotation_swaps_aspect_ratio.
    // get_text_layout must apply the same SetPageRotation-before-size-query
    // ordering render_page uses, so page_width_pt/height_pt and every run's
    // bbox land within that swapped extent, not the original portrait one.
    const auto path = std::string("quickmarkpdf_test_text_layout_rotated.pdf");
    write_text_pdf(path, "Hi", /*text_x=*/10, /*text_y=*/50, /*page_width=*/100, /*page_height=*/200);

    const auto layout = quickmarkpdf::PdfBackend::get_text_layout(path, 0, /*rotation=*/90);
    assert(layout.page_width_pt == 200.0);
    assert(layout.page_height_pt == 100.0);
    assert(!layout.runs.empty());
    for (const auto& run : layout.runs) {
        assert(run.x0 >= 0 && run.x1 <= layout.page_width_pt);
        assert(run.y0 >= 0 && run.y1 <= layout.page_height_pt);
    }

    std::remove(path.c_str());
}

void test_inspect_rejects_corrupted_pdf() {
    // A byte sequence with no %PDF header and no xref/trailer at all --
    // pdfium's FPDF_LoadMemDocument64 fails to parse it and reports
    // FPDF_ERR_FORMAT, which PdfBackend::inspect (via open_source() in
    // pdf_backend.cpp) wraps as a std::runtime_error whose message embeds
    // describe_error(FPDF_ERR_FORMAT) == "file is not a PDF or is
    // corrupted" (verified against the current pdf_backend.cpp, not assumed).
    const auto path = std::string("quickmarkpdf_test_corrupted.pdf");
    {
        std::ofstream out(path, std::ios::binary);
        out << "this is not a PDF file at all -- just plain garbage bytes 0123456789, "
               "no %PDF header, no xref table, nothing pdfium can parse.";
    }

    bool threw = false;
    try {
        quickmarkpdf::PdfBackend::inspect(path);
    } catch (const std::runtime_error& e) {
        threw = true;
        const std::string message = e.what();
        assert(message.find("not a PDF") != std::string::npos ||
               message.find("corrupted") != std::string::npos);
    }
    assert(threw);

    std::remove(path.c_str());
}

void test_inspect_requires_password_for_encrypted_pdf() {
    // kEncryptedFixturePdf (defined above, near write_min_pdf) is a real
    // AES-128-encrypted 2-page PDF generated once via PyMuPDF with user
    // password "secret123" -- PdfBackend::inspect must refuse it both with
    // no password and with a wrong one (throwing PdfPasswordRequiredError,
    // per pdf_backend.h/.cpp's open_source() handling of FPDF_ERR_PASSWORD),
    // and must succeed and report the correct page count with the right one.
    const auto path = std::string("quickmarkpdf_test_encrypted.pdf");
    write_encrypted_fixture_pdf(path);

    bool threw_no_password = false;
    try {
        quickmarkpdf::PdfBackend::inspect(path);
    } catch (const quickmarkpdf::PdfPasswordRequiredError& e) {
        threw_no_password = true;
        assert(e.path() == path);
        assert(std::string(e.what()).find("password") != std::string::npos);
    }
    assert(threw_no_password);

    bool threw_wrong_password = false;
    try {
        quickmarkpdf::PdfBackend::inspect(path, "wrong-password");
    } catch (const quickmarkpdf::PdfPasswordRequiredError&) {
        threw_wrong_password = true;
    }
    assert(threw_wrong_password);

    const auto info = quickmarkpdf::PdfBackend::inspect(path, "secret123");
    assert(info.page_count == 2);

    std::remove(path.c_str());
}

// ---------------------------------------------------------------------
// PdfManager: mirrors python/src/pdf_editor/pdf/pdf_manager.py's own test
// suite (tests/test_pdf_manager.py) at the orchestration level -- load
// dedup/passwords, overwrite/save-as, image export, close-one-source, and
// undo integration through this layer.
// ---------------------------------------------------------------------

std::pair<int, int> read_png_dimensions(const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    std::array<unsigned char, 24> header{};
    in.read(reinterpret_cast<char*>(header.data()), static_cast<std::streamsize>(header.size()));
    auto be32 = [&](int offset) {
        return (static_cast<unsigned>(header[static_cast<std::size_t>(offset)]) << 24) |
               (static_cast<unsigned>(header[static_cast<std::size_t>(offset) + 1]) << 16) |
               (static_cast<unsigned>(header[static_cast<std::size_t>(offset) + 2]) << 8) |
               static_cast<unsigned>(header[static_cast<std::size_t>(offset) + 3]);
    };
    return {static_cast<int>(be32(16)), static_cast<int>(be32(20))};
}

void test_manager_load_and_count() {
    const auto p1 = std::string("quickmarkpdf_test_mgr_a.pdf");
    const auto p2 = std::string("quickmarkpdf_test_mgr_b.pdf");
    write_min_pdf(p1, 3);
    write_min_pdf(p2, 2);

    PdfManager mgr;
    const auto result = mgr.load_pdfs({p1, p2});
    assert(result.loaded_count == 2);
    assert(result.password_required.empty());
    assert(result.duplicate_files.empty());
    assert(mgr.get_page_count() == 5);

    std::remove(p1.c_str());
    std::remove(p2.c_str());
}

void test_manager_loading_an_already_open_file_again_is_skipped() {
    const auto p1 = std::string("quickmarkpdf_test_mgr_dup_a.pdf");
    const auto p2 = std::string("quickmarkpdf_test_mgr_dup_b.pdf");
    write_min_pdf(p1, 3);
    write_min_pdf(p2, 2);

    PdfManager mgr;
    mgr.load_pdfs({p1});
    assert(mgr.get_page_count() == 3);

    const auto result = mgr.load_pdfs({p1, p2});
    assert(result.loaded_count == 1);  // only p2 actually loaded
    assert(result.duplicate_files.size() == 1);
    assert(mgr.get_page_count() == 5);

    std::remove(p1.c_str());
    std::remove(p2.c_str());
}

void test_manager_selecting_the_same_file_twice_in_one_call_is_deduped() {
    const auto p1 = std::string("quickmarkpdf_test_mgr_samecall.pdf");
    write_min_pdf(p1, 3);

    PdfManager mgr;
    const auto result = mgr.load_pdfs({p1, p1});
    assert(result.loaded_count == 1);
    assert(result.duplicate_files.size() == 1);
    assert(mgr.get_page_count() == 3);

    std::remove(p1.c_str());
}

void test_manager_delete_pages_multiple_and_out_of_range() {
    const auto p1 = std::string("quickmarkpdf_test_mgr_delete.pdf");
    write_min_pdf(p1, 3);

    PdfManager mgr;
    mgr.load_pdfs({p1});
    mgr.delete_pages({0, 2, 99});  // 99 is out of range and must be ignored, not thrown
    assert(mgr.get_page_count() == 1);
    assert(mgr.page_infos()[0].original_page_index == 1);

    std::remove(p1.c_str());
}

void test_manager_can_overwrite_source_only_with_single_file() {
    const auto p1 = std::string("quickmarkpdf_test_mgr_ovw_a.pdf");
    const auto p2 = std::string("quickmarkpdf_test_mgr_ovw_b.pdf");
    write_min_pdf(p1, 2);
    write_min_pdf(p2, 1);

    PdfManager mgr;
    mgr.load_pdfs({p1});
    assert(mgr.can_overwrite_source());

    mgr.load_pdfs({p2});
    assert(!mgr.can_overwrite_source());

    std::remove(p1.c_str());
    std::remove(p2.c_str());
}

void test_manager_overwrite_source_replaces_file_and_reloads() {
    const auto p1 = std::string("quickmarkpdf_test_mgr_ovw_replace.pdf");
    write_min_pdf(p1, 3);

    PdfManager mgr;
    mgr.load_pdfs({p1});
    mgr.rotate_page(0, 90);

    const bool ok = mgr.overwrite_source();
    assert(ok);
    assert(mgr.get_page_count() == 3);
    assert(mgr.page_infos()[0].rotation == 90);

    // No leftover temp file next to the source.
    bool leftover_found = false;
    for (const auto& entry : std::filesystem::directory_iterator(std::filesystem::current_path())) {
        if (entry.path().filename().u8string().find(".tmp_quickmarkpdf") != std::string::npos) {
            leftover_found = true;
        }
    }
    assert(!leftover_found);

    // Independently confirm the on-disk file was actually rewritten with
    // the rotation applied.
    const auto info = quickmarkpdf::PdfBackend::inspect(p1);
    assert(info.page_count == 3);
    assert(info.page_rotations[0] == 90);

    std::remove(p1.c_str());
}

void test_manager_save_as_creates_new_file_without_touching_sources() {
    const auto p1 = std::string("quickmarkpdf_test_mgr_saveas.pdf");
    const auto out = std::string("quickmarkpdf_test_mgr_saveas_out.pdf");
    write_min_pdf(p1, 2);

    PdfManager mgr;
    mgr.load_pdfs({p1});
    mgr.reorder_pages({1, 0});

    const bool ok = mgr.save_as(out);
    assert(ok);

    const auto info = quickmarkpdf::PdfBackend::inspect(out);
    assert(info.page_count == 2);

    std::remove(p1.c_str());
    std::remove(out.c_str());
}

void test_manager_save_selected_pages_cuts_out_a_new_pdf() {
    // Matches Python's split_document()/save_selected_pages(): cut out a
    // subset of pages (in the given order) into a brand-new file, leaving
    // the open document and its undo history untouched.
    const auto p1 = std::string("quickmarkpdf_test_mgr_cutout.pdf");
    const auto out = std::string("quickmarkpdf_test_mgr_cutout_out.pdf");
    write_min_pdf(p1, 4);

    PdfManager mgr;
    mgr.load_pdfs({p1});
    mgr.rotate_page(2, 90);
    const bool had_undo_before = mgr.can_undo();

    const bool ok = mgr.save_selected_pages({2, 0}, out);
    assert(ok);
    assert(mgr.get_page_count() == 4);              // source document untouched
    assert(mgr.can_undo() == had_undo_before);       // no new undo step from cutting out

    const auto info = quickmarkpdf::PdfBackend::inspect(out);
    assert(info.page_count == 2);
    assert(info.page_rotations[0] == 90);  // was page index 2, rotated
    assert(info.page_rotations[1] == 0);   // was page index 0

    std::remove(p1.c_str());
    std::remove(out.c_str());
}

void test_manager_save_selected_pages_rejects_empty_selection() {
    const auto p1 = std::string("quickmarkpdf_test_mgr_cutout_empty.pdf");
    write_min_pdf(p1, 2);

    PdfManager mgr;
    mgr.load_pdfs({p1});
    assert(!mgr.save_selected_pages({}, "quickmarkpdf_should_not_exist.pdf"));

    std::remove(p1.c_str());
}

void test_manager_export_images_with_clip() {
    // Matches tests/test_pdf_manager.py::test_export_images_with_clip: a
    // 200x300pt page, a 100x100pt crop at (10,10), 72 DPI (1pt == 1px) ->
    // expect a 100x100px PNG.
    const auto p1 = std::string("quickmarkpdf_test_mgr_export.pdf");
    write_min_pdf(p1, 1, 200, 300);
    const auto out_dir = std::string("quickmarkpdf_test_mgr_export_out");

    PdfManager mgr;
    mgr.load_pdfs({p1});

    const auto result = mgr.export_pages_to_images(
        {0}, out_dir, "png", /*dpi=*/72, "test_clip",
        std::array<double, 4>{10, 10, 110, 110});
    assert(result.success == 1);
    assert(result.attempted == 1);
    assert(result.errors.empty());

    const auto out_file = out_dir + "/test_clip_0001.png";
    const auto dims = read_png_dimensions(out_file);
    assert(dims.first == 100);
    assert(dims.second == 100);

    std::remove(out_file.c_str());
    std::filesystem::remove(out_dir);
    std::remove(p1.c_str());
}

void test_manager_export_images_as_jpeg() {
    // No hand-rolled JPEG decoder is available to check exact pixel
    // dimensions here (unlike the PNG test, which reads IHDR directly), so
    // this checks what's practical without one: the file exists, is a
    // plausible size, and starts/ends with the JPEG SOI/EOI markers --
    // enough to catch "WIC silently wrote garbage or nothing."
    const auto p1 = std::string("quickmarkpdf_test_mgr_export_jpeg.pdf");
    write_min_pdf(p1, 1, 200, 300);
    const auto out_dir = std::string("quickmarkpdf_test_mgr_export_jpeg_out");

    PdfManager mgr;
    mgr.load_pdfs({p1});

    const auto result = mgr.export_pages_to_images({0}, out_dir, "jpg", /*dpi=*/72, "photo", std::nullopt,
                                                     /*jpeg_quality=*/85);
    assert(result.success == 1);
    assert(result.attempted == 1);
    assert(result.errors.empty());

    const auto out_file = out_dir + "/photo_0001.jpg";
    std::ifstream in(out_file, std::ios::binary);
    const std::vector<unsigned char> bytes((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
    in.close();
    assert(bytes.size() > 100);
    assert(bytes[0] == 0xFF && bytes[1] == 0xD8);  // SOI
    assert(bytes[bytes.size() - 2] == 0xFF && bytes[bytes.size() - 1] == 0xD9);  // EOI

    std::remove(out_file.c_str());
    std::filesystem::remove(out_dir);
    std::remove(p1.c_str());
}

void test_manager_password_flow() {
    const auto path = std::string("quickmarkpdf_test_mgr_password.pdf");
    write_encrypted_fixture_pdf(path);

    PdfManager mgr;
    auto no_password = mgr.load_pdfs({path});
    assert(no_password.loaded_count == 0);
    assert(no_password.password_required.size() == 1);
    assert(mgr.get_page_count() == 0);

    auto wrong_password = mgr.load_pdfs({path}, {{path, "wrong"}});
    assert(wrong_password.loaded_count == 0);
    assert(wrong_password.password_required.size() == 1);

    auto correct_password = mgr.load_pdfs({path}, {{path, "secret123"}});
    assert(correct_password.loaded_count == 1);
    assert(correct_password.password_required.empty());
    assert(mgr.get_page_count() == 2);

    std::remove(path.c_str());
}

void test_manager_undo_reorder_and_rotate_and_delete() {
    const auto p1 = std::string("quickmarkpdf_test_mgr_undo.pdf");
    write_min_pdf(p1, 3);

    PdfManager mgr;
    mgr.load_pdfs({p1});
    const auto original = mgr.page_infos();

    mgr.reorder_pages({2, 1, 0});
    assert(mgr.page_infos()[0].original_page_index != original[0].original_page_index);
    assert(mgr.undo());
    assert(mgr.page_infos()[0].original_page_index == original[0].original_page_index);

    mgr.rotate_pages({0, 1, 2}, 90);
    assert(mgr.page_infos()[0].rotation == 90);
    assert(mgr.undo());
    assert(mgr.page_infos()[0].rotation == 0);

    mgr.delete_pages({1});
    assert(mgr.get_page_count() == 2);
    assert(mgr.undo());
    assert(mgr.get_page_count() == 3);

    std::remove(p1.c_str());
}

void test_manager_close_document_removes_only_its_pages_and_is_undoable() {
    const auto p1 = std::string("quickmarkpdf_test_mgr_close_a.pdf");
    const auto p2 = std::string("quickmarkpdf_test_mgr_close_b.pdf");
    write_min_pdf(p1, 2);
    write_min_pdf(p2, 2);

    PdfManager mgr;
    mgr.load_pdfs({p1, p2});
    assert(mgr.get_page_count() == 4);

    const bool closed = mgr.close_document(p1);
    assert(closed);
    assert(mgr.get_page_count() == 2);
    for (const auto& info : mgr.page_infos()) {
        assert(info.source_path.find(
            std::filesystem::absolute(std::filesystem::u8path(p2)).u8string()) != std::string::npos);
    }

    assert(mgr.undo());
    assert(mgr.get_page_count() == 4);

    assert(!mgr.close_document("quickmarkpdf_no_such_file.pdf"));

    std::remove(p1.c_str());
    std::remove(p2.c_str());
}

void test_manager_clear_undo_history_keeps_pages() {
    const auto p1 = std::string("quickmarkpdf_test_mgr_clearundo.pdf");
    write_min_pdf(p1, 2);

    PdfManager mgr;
    mgr.load_pdfs({p1});
    mgr.rotate_page(0, 90);
    assert(mgr.can_undo());

    mgr.clear_undo_history();
    assert(!mgr.can_undo());
    assert(mgr.get_page_count() == 2);  // pages themselves are untouched

    std::remove(p1.c_str());
}

void test_manager_close_all_clears_everything() {
    const auto p1 = std::string("quickmarkpdf_test_mgr_closeall.pdf");
    write_min_pdf(p1, 2);

    PdfManager mgr;
    mgr.load_pdfs({p1});
    mgr.rotate_page(0, 90);
    assert(mgr.can_undo());

    mgr.close_all();
    assert(mgr.get_page_count() == 0);
    assert(!mgr.can_undo());

    std::remove(p1.c_str());
}

}  // namespace

int main() {
    test_append_and_rotation_normalization();
    test_reorder_and_erase();
    test_invalid_operations_are_rejected();
    test_no_undo_available_initially();
    test_undo_reorder();
    test_undo_delete_pages();
    test_undo_rotate_restores_actual_rotation();
    test_invalid_rotate_does_not_create_undo_step();
    test_undo_stack_capped();
    test_clear_wipes_undo_history_and_dirty_flag();
    test_dirty_tracks_unsaved_changes();
    test_pdf_inspection_boundary();
    test_inspect_reports_each_pages_own_rotation();
    test_save_merges_reorders_and_rotates_pages();
    test_save_reports_missing_source_file();
    test_render_page_produces_blank_white_bitmap();
    test_render_page_rotation_swaps_aspect_ratio();
    test_render_page_at_dpi_matches_pdf_point_size();
    test_get_text_layout_extracts_text_and_bbox();
    test_get_text_layout_empty_for_blank_page();
    test_get_text_layout_rotation_keeps_bbox_within_rotated_page();
    test_inspect_rejects_corrupted_pdf();
    test_inspect_requires_password_for_encrypted_pdf();

    test_manager_load_and_count();
    test_manager_loading_an_already_open_file_again_is_skipped();
    test_manager_selecting_the_same_file_twice_in_one_call_is_deduped();
    test_manager_delete_pages_multiple_and_out_of_range();
    test_manager_can_overwrite_source_only_with_single_file();
    test_manager_overwrite_source_replaces_file_and_reloads();
    test_manager_save_as_creates_new_file_without_touching_sources();
    test_manager_save_selected_pages_cuts_out_a_new_pdf();
    test_manager_save_selected_pages_rejects_empty_selection();
    test_manager_export_images_with_clip();
    test_manager_export_images_as_jpeg();
    test_manager_password_flow();
    test_manager_undo_reorder_and_rotate_and_delete();
    test_manager_close_document_removes_only_its_pages_and_is_undoable();
    test_manager_clear_undo_history_keeps_pages();
    test_manager_close_all_clears_everything();

    std::puts("All engine_tests assertions passed.");
    return 0;
}
