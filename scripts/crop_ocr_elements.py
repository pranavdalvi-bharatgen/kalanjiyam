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
    DEFAULT_IMAGE_TYPES
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

    # Load layout JSON
    with open(json_path, encoding='utf-8') as f:
        layout_data = json.load(f)

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
