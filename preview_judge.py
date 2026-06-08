"""
Preview Image Judge for automatic verification of the close-file bug fix.

Usage:
  python preview_judge.py debug_close_xxx.png
  python preview_judge.py debug_close_*.png --reference reference_default_preview.png

It analyzes the captured preview_label image and outputs a verdict:
  - DEFAULT_TEXT : Preview is cleared to the default placeholder text (good after close when no specific page selected)
  - SHOWING_PAGE_CONTENT : A page is being rendered in the preview (could be next file's first page, or bug if old content)
  - LIKELY_OLD_PAGE : High similarity to a provided "old_page_reference.png" (use when you have a capture of the page before close)

It also prints a confidence score and simple metrics.

This is a lightweight tool using only Pillow (no heavy CV libs).
It is meant to be run after the PDF Editor auto-saves debug images on file close.

The tool helps answer:
- Is the right-side preview still showing a page from the just-closed file? (FAIL for the reported bug)
- Has it switched to default/blank or a new page?

For best results:
1. Once, with the app in default state (no file open or after clear), run the editor and save a reference:
   (the app can auto-save "reference_default_preview.png" on startup with 0 pages)
2. Before closing a file, optionally capture the current preview as "old_page_reference.png"
3. Close the file from the tree.
4. Run this judge on the auto-saved debug_preview_after_close_*.png
"""

import sys
import os
from pathlib import Path
from PIL import Image, ImageChops, ImageStat, ImageFilter
import argparse
import json

def load_image(path):
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    return Image.open(path).convert("RGB")

def compute_difference(img1, img2):
    """Return normalized mean absolute difference (0.0 = identical, 1.0 = completely different)."""
    if img1.size != img2.size:
        img2 = img2.resize(img1.size, Image.Resampling.LANCZOS)
    diff = ImageChops.difference(img1, img2)
    stat = ImageStat.Stat(diff)
    # Average over channels
    mean_diff = sum(stat.mean) / len(stat.mean)
    # Normalize by max possible per channel (255)
    return mean_diff / 255.0

def has_text_like_structure(img, threshold=0.15):
    """
    Very rough heuristic: after edge detection, see if there is significant structure
    consistent with readable text on the default dark background.
    """
    gray = img.convert("L")
    edges = gray.filter(ImageFilter.FIND_EDGES)
    stat = ImageStat.Stat(edges)
    edge_density = stat.mean[0] / 255.0
    return edge_density > threshold

def is_mostly_dark_with_centered_content(img, dark_threshold=60, content_ratio=0.3):
    """
    Heuristic for "default text state": mostly dark background, with some light content
    roughly in the center (where the placeholder text is drawn).
    """
    gray = img.convert("L")
    pixels = list(gray.getdata())
    dark_pixels = sum(1 for p in pixels if p < dark_threshold)
    dark_ratio = dark_pixels / len(pixels)

    # Check central region for content
    w, h = gray.size
    cx, cy = w // 2, h // 2
    box_size = min(w, h) // 3
    central = gray.crop((cx - box_size, cy - box_size // 2, cx + box_size, cy + box_size // 2))
    central_stat = ImageStat.Stat(central)
    central_avg = central_stat.mean[0]

    return (dark_ratio > 0.75) and (central_avg > 80)  # some light content in center

def judge_preview_image(image_path, reference_default_path=None, old_page_reference_path=None):
    img = load_image(image_path)
    w, h = img.size

    # If the image is a full window/desktop screenshot (wide), crop the right side
    # assuming the preview is on the right half of the splitter.
    if w > 800:  # likely full app or desktop
        crop_x = int(w * 0.45)  # rough right 55%
        img = img.crop((crop_x, 0, w, h))
        w, h = img.size  # update size after crop

    result = {
        "image": str(image_path),
        "size": f"{w}x{h}",
        "verdict": "UNCLEAR",
        "confidence": 0.0,
        "metrics": {},
        "explanation": ""
    }

    # Basic metrics
    gray = img.convert("L")
    stat = ImageStat.Stat(gray)
    avg_brightness = stat.mean[0]
    result["metrics"]["avg_brightness"] = round(avg_brightness, 1)

    edge_img = gray.filter(ImageFilter.FIND_EDGES)
    edge_stat = ImageStat.Stat(edge_img)
    edge_density = edge_stat.mean[0] / 255.0
    result["metrics"]["edge_density"] = round(edge_density, 3)

    # Compare to default reference if available
    if reference_default_path and os.path.exists(reference_default_path):
        ref = load_image(reference_default_path)
        diff = compute_difference(img, ref)
        result["metrics"]["diff_to_default"] = round(diff, 3)

        if diff < 0.12:
            result["verdict"] = "DEFAULT_TEXT"
            result["confidence"] = 1.0 - (diff * 4)
            result["explanation"] = "Very similar to the default placeholder state (good after close)."
            return result

    # Heuristics for default text vs page content
    looks_like_default = is_mostly_dark_with_centered_content(img)
    has_page_structure = edge_density > 0.08 and avg_brightness > 40  # typical rendered page

    if looks_like_default and not has_page_structure:
        result["verdict"] = "DEFAULT_TEXT"
        result["confidence"] = 0.85
        result["explanation"] = "Dark background + centered light content consistent with default text. Preview appears cleared."
    elif has_page_structure:
        # Looks like a rendered page
        if old_page_reference_path and os.path.exists(old_page_reference_path):
            old_ref = load_image(old_page_reference_path)
            diff_to_old = compute_difference(img, old_ref)
            result["metrics"]["diff_to_old_page"] = round(diff_to_old, 3)
            if diff_to_old < 0.25:
                result["verdict"] = "STILL_SHOWING_OLD_PAGE"
                result["confidence"] = 0.9 - diff_to_old
                result["explanation"] = "High similarity to the provided old page reference. Bug may still be present."
            else:
                result["verdict"] = "SHOWING_PAGE_CONTENT"
                result["confidence"] = 0.75
                result["explanation"] = "Showing page-like content, different from the old reference (likely next file's first page)."
        else:
            result["verdict"] = "SHOWING_PAGE_CONTENT"
            result["confidence"] = 0.7
            result["explanation"] = "Detected page-like structure (bright content with edges). Could be next file or still old (provide old_page_reference for better distinction)."
    else:
        result["verdict"] = "UNCLEAR"
        result["confidence"] = 0.4
        result["explanation"] = "Could not confidently classify. Check the image manually."

    return result

def main():
    parser = argparse.ArgumentParser(description="Judge what is shown in a captured preview_label image after file close.")
    parser.add_argument("images", nargs="+", help="Path(s) to debug_preview_*.png or similar captured preview images.")
    parser.add_argument("--reference-default", default="reference_default_preview.png",
                        help="Path to a reference image of the default/cleared preview state.")
    parser.add_argument("--old-page-reference", default=None,
                        help="Optional path to a screenshot of the specific page that was being viewed before the close (to detect if old content remains).")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON instead of human text.")

    args = parser.parse_args()

    results = []
    for img_path in args.images:
        try:
            res = judge_preview_image(
                img_path,
                reference_default_path=args.reference_default if os.path.exists(args.reference_default) else None,
                old_page_reference_path=args.old_page_reference
            )
            results.append(res)
            if not args.json:
                print(f"\n=== {img_path} ===")
                print(f"Verdict: {res['verdict']} (confidence: {res['confidence']:.0%})")
                print(f"Explanation: {res['explanation']}")
                print(f"Metrics: {res['metrics']}")
        except Exception as e:
            print(f"Error processing {img_path}: {e}")

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))

    # Simple overall summary for CI-like use
    if results:
        all_cleared = all(r["verdict"] in ("DEFAULT_TEXT", "SHOWING_PAGE_CONTENT") for r in results)
        still_old = any(r["verdict"] == "STILL_SHOWING_OLD_PAGE" for r in results)
        if still_old:
            print("\n[RESULT] FAIL: At least one capture still shows old page content.")
            sys.exit(1)
        elif all_cleared:
            print("\n[RESULT] PASS: Previews appear cleared or showing new content (not the closed file's page).")
            sys.exit(0)
        else:
            print("\n[RESULT] UNCLEAR: Manual review of images recommended.")
            sys.exit(2)

if __name__ == "__main__":
    main()