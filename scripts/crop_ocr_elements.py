#!/usr/bin/env python3
"""
crop_ocr_elements.py

A Python utility to parse GLM-OCR layout JSON files, scale and crop document visual elements
(figures, images, diagrams, pictures) using PyMuPDF and Pillow.
"""

import os
import sys
import json
import argparse
from pathlib import Path
from typing import List

# Ensure repository root is on sys.path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

# Import cropping logic from app package
from kalanjiyam.utils.ocr_cropper import (
    crop_elements_from_image,
    crop_elements_from_pdf,
    DEFAULT_IMAGE_TYPES,
    is_image_block,
)

def process_document(
    doc_path: str,
    json_path: str,
    output_dir: str,
    page_num: int = 0,
    project_slug: str | None = None,
    save_json_path: str | None = None,
    use_caption_naming: bool = False,
) -> List[str]:
    """
    Helper function to load the JSON payload, check file type of doc_path, and route to proper cropper.
    """
    if not os.path.exists(doc_path):
        raise FileNotFoundError(f"Source document not found: {doc_path}")
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"JSON layout file not found: {json_path}")

    # Load layout JSON or HTML
    raw_content = Path(json_path).read_text(encoding="utf-8").strip()
    layout_data = None
    if raw_content.startswith("{") or raw_content.startswith("["):
        try:
            layout_data = json.loads(raw_content)
        except json.JSONDecodeError:
            pass

    if layout_data is None:
        layout_data = {"text": raw_content}

    # Support Chandra OCR HTML content and bounding_boxes fallback
    if isinstance(layout_data, dict) and not layout_data.get("blocks"):
        html_candidate = layout_data.get("layout_html") or layout_data.get("html") or layout_data.get("text")
        if html_candidate and any(k in html_candidate.lower() for k in ("data-bbox", "data-box", "bbox=", "<figure", "<img")):
            from kalanjiyam.utils.ocr_client import _parse_chandra_html
            p_blocks, _, _ = _parse_chandra_html(html_candidate, layout_data.get("page_width"), layout_data.get("page_height"))
            if p_blocks:
                layout_data["blocks"] = p_blocks

        if not layout_data.get("blocks") and layout_data.get("bounding_boxes"):
            blocks = []
            for idx, box in enumerate(layout_data["bounding_boxes"]):
                if isinstance(box, (list, tuple)) and len(box) >= 5 and is_image_block(box[4]):
                    blocks.append({
                        "id": f"b{idx+1:03d}",
                        "type": "figure",
                        "bbox": [float(box[0]), float(box[1]), float(box[2]), float(box[3])],
                        "content": "",
                    })
                elif isinstance(box, dict):
                    btype = box.get("label") or box.get("type") or box.get("category") or ""
                    bbox = box.get("bbox")
                    if bbox and is_image_block(btype):
                        blocks.append({
                            "id": box.get("id") or f"b{idx+1:03d}",
                            "type": "figure",
                            "bbox": [float(x) for x in bbox],
                            "content": "",
                        })
            if blocks:
                layout_data["blocks"] = blocks

    # Route based on extension/type
    ext = os.path.splitext(doc_path)[1].lower()
    
    if ext == ".pdf":
        results = crop_elements_from_pdf(
            pdf_path=doc_path,
            layout_data=layout_data,
            project_slug=project_slug,
            output_dir=output_dir,
            page_num=page_num,
            use_caption_naming=use_caption_naming,
        )
    else:
        # Attempt to open as image
        try:
            results = crop_elements_from_image(
                image_path=doc_path,
                layout_data=layout_data,
                project_slug=project_slug,
                output_dir=output_dir,
                use_caption_naming=use_caption_naming,
            )
        except Exception as e:
            raise ValueError(f"Unsupported document format or error loading file as image: {doc_path}. Error: {e}")

    if save_json_path:
        with open(save_json_path, "w", encoding="utf-8") as out_f:
            json.dump(layout_data, out_f, indent=2, ensure_ascii=False)

    return results

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Crop visual elements from a document using GLM-OCR layout coordinates.")
    parser.add_argument("--doc", required=True, help="Path to the source document (PDF or Image)")
    parser.add_argument("--json-file", required=True, help="Path to the GLM-OCR layout JSON response")
    parser.add_argument("--output-dir", default="extracted_elements", help="Directory to save the cropped images")
    parser.add_argument("--page", type=int, default=0, help="PDF page index to crop from (0-indexed, default is 0)")
    parser.add_argument("--project-slug", default=None, help="Optional Kalanjiyam project slug to save into app storage")
    parser.add_argument("--save-json", default=None, help="Optional file path to save updated layout JSON")
    parser.add_argument("--use-caption-naming", action="store_true", help="Name extracted figure images based on detected figure caption text")

    args = parser.parse_args()

    try:
        results = process_document(
            doc_path=args.doc,
            json_path=args.json_file,
            output_dir=args.output_dir,
            page_num=args.page,
            project_slug=args.project_slug,
            save_json_path=args.save_json,
            use_caption_naming=args.use_caption_naming,
        )
        print(f"\nSuccessfully cropped {len(results)} visual element(s).")
    except Exception as exc:
        print(f"\nError processing document: {exc}")
        exit(1)
