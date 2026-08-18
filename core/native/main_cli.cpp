#include "engine.h"

#include <iostream>
#include <string>
#include <vector>

namespace {
void print_help() {
    std::cout << "QuickMarkPDF native core demo\n"
              << "Usage: QuickMarkPDF_cli.exe [demo|--help]\n\n"
              << "The demo exercises the C++ page model used by the upcoming PDF engine.\n";
}

void print_pages(const quickmarkpdf::WorkingDocument& document, const char* label) {
    std::cout << label << " (" << document.page_count() << " pages)\n";
    for (std::size_t i = 0; i < document.page_count(); ++i) {
        const auto& page = document.page(i);
        std::cout << "  [" << i << "] " << page.source_path
                  << " page=" << page.source_page
                  << " rotation=" << page.rotation << "\n";
    }
}
}  // namespace

int main(int argc, char* argv[]) {
    if (argc > 1 && std::string(argv[1]) == "--help") {
        print_help();
        return 0;
    }
    if (argc > 1 && std::string(argv[1]) != "demo") {
        std::cerr << "Unknown command: " << argv[1] << "\n\n";
        print_help();
        return 2;
    }

    quickmarkpdf::WorkingDocument document;
    document.append_page({"report.pdf", 0, 0});
    document.append_page({"report.pdf", 1, 0});
    document.append_page({"invoice.pdf", 0, 0});
    print_pages(document, "Loaded working document");

    document.reorder({2, 0, 1});
    document.rotate(0, 90);
    document.erase({2});
    print_pages(document, "After reorder, rotate, and delete");
    return 0;
}
