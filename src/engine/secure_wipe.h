#pragma once

#include <string>

#include <windows.h>

namespace quickmarkpdf {

// Zeroes a secret (e.g. a PDF password) in place before releasing it.
// SecureZeroMemory is not optimized away, unlike a plain memset/fill.
inline void secure_wipe(std::string& value) noexcept {
    if (!value.empty()) SecureZeroMemory(value.data(), value.size());
    value.clear();
}

inline void secure_wipe(std::wstring& value) noexcept {
    if (!value.empty()) SecureZeroMemory(value.data(), value.size() * sizeof(wchar_t));
    value.clear();
}

}  // namespace quickmarkpdf
