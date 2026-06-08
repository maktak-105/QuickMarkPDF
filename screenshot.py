"""
Screenshot utility for Windows.
Captures the full desktop or a specific window by title.
Uses only stdlib + Pillow (which is in the project's requirements).

Usage:
  python screenshot.py                    # full screen, timestamped filename
  python screenshot.py "PDF Editor"       # capture window with title containing "PDF Editor"
  python screenshot.py --help

Saves PNG to current dir.
"""

import ctypes
from ctypes import wintypes
from PIL import Image
import datetime
import sys
import os

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

# Structures
class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]

class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", wintypes.DWORD * 3),
    ]

def capture_full_screen():
    """Capture the entire desktop."""
    screen_width = user32.GetSystemMetrics(0)
    screen_height = user32.GetSystemMetrics(1)

    hdc = user32.GetDC(0)
    hdc_mem = gdi32.CreateCompatibleDC(hdc)
    hbm = gdi32.CreateCompatibleBitmap(hdc, screen_width, screen_height)
    gdi32.SelectObject(hdc_mem, hbm)

    # SRCCOPY
    gdi32.BitBlt(hdc_mem, 0, 0, screen_width, screen_height, hdc, 0, 0, 0x00CC0020)

    bmp_info = BITMAPINFO()
    bmp_info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmp_info.bmiHeader.biWidth = screen_width
    bmp_info.bmiHeader.biHeight = -screen_height  # negative for top-down
    bmp_info.bmiHeader.biPlanes = 1
    bmp_info.bmiHeader.biBitCount = 32
    bmp_info.bmiHeader.biCompression = 0  # BI_RGB

    buffer_size = screen_width * screen_height * 4
    buffer = (ctypes.c_char * buffer_size)()

    gdi32.GetDIBits(hdc_mem, hbm, 0, screen_height, buffer, ctypes.byref(bmp_info), 0)

    # Create image (BGRA -> RGBA)
    image = Image.frombuffer("RGBA", (screen_width, screen_height), buffer, "raw", "BGRA", 0, 1)

    # Cleanup
    gdi32.DeleteObject(hbm)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(0, hdc)

    return image

def capture_window_by_title(title_substring):
    """Capture a window whose title contains the given substring (case-insensitive).
    Falls back to full screen if no matching window or on error.
    """
    found_hwnds = []

    def enum_windows_proc(hwnd, lparam):
        try:
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buff, length + 1)
                    if title_substring.lower() in buff.value.lower():
                        found_hwnds.append(hwnd)
        except Exception:
            pass  # Ignore errors in callback
        return True

    try:
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows(WNDENUMPROC(enum_windows_proc), 0)

        if not found_hwnds:
            print(f"No visible window found with title containing '{title_substring}', falling back to full screen.")
            return capture_full_screen()

        hwnd = found_hwnds[0]

        # Get window rect
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        width = rect.right - rect.left
        height = rect.bottom - rect.top

        if width <= 0 or height <= 0:
            print("Invalid window dimensions, falling back to full screen.")
            return capture_full_screen()

        # Capture the window
        hdc = user32.GetWindowDC(hwnd)
        hdc_mem = gdi32.CreateCompatibleDC(hdc)
        hbm = gdi32.CreateCompatibleBitmap(hdc, width, height)
        gdi32.SelectObject(hdc_mem, hbm)

        gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc, 0, 0, 0x00CC0020)

        bmp_info = BITMAPINFO()
        bmp_info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmp_info.bmiHeader.biWidth = width
        bmp_info.bmiHeader.biHeight = -height
        bmp_info.bmiHeader.biPlanes = 1
        bmp_info.bmiHeader.biBitCount = 32
        bmp_info.bmiHeader.biCompression = 0

        buffer_size = width * height * 4
        buffer = (ctypes.c_char * buffer_size)()

        gdi32.GetDIBits(hdc_mem, hbm, 0, height, buffer, ctypes.byref(bmp_info), 0)

        image = Image.frombuffer("RGBA", (width, height), buffer, "raw", "BGRA", 0, 1)

        gdi32.DeleteObject(hbm)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(hwnd, hdc)

        return image
    except Exception as e:
        print(f"Window capture failed ({e}), falling back to full screen.")
        return capture_full_screen()

def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return

    if len(sys.argv) > 1:
        title = sys.argv[1]
        print(f"Capturing window containing title: {title}")
        image = capture_window_by_title(title)
    else:
        print("Capturing full desktop...")
        image = capture_full_screen()

    if image is None:
        print("Failed to capture image.")
        return

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"screenshot_{timestamp}.png"
    image.save(filename)
    print(f"Saved: {os.path.abspath(filename)}")

if __name__ == "__main__":
    main()