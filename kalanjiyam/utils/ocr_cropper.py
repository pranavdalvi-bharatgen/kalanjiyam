import os
import io
import re
import uuid
import logging
import unicodedata
from typing import List, Dict, Any, Optional
from PIL import Image
import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

DEFAULT_IMAGE_TYPES = {"figure", "image", "picture", "diagram"}


def slugify_figure_name(caption: str, max_length: int = 50) -> str:
    """
    Sanitize and slugify a figure caption into a clean, safe filename component.
    Preserves alphanumeric and combining unicode characters across scripts
    (Latin, Devanagari, Tamil, etc.).
    """
    if not caption:
        return ""
    from bs4 import BeautifulSoup

    text = BeautifulSoup(caption, "html.parser").get_text().strip()
    text = unicodedata.normalize("NFC", text)
    # Keep Unicode Letters (L), Marks/Matras (M), Numbers (N), and hyphens/underscores
    result = []
    for ch in text:
        cat = unicodedata.category(ch)
        if cat[0] in ("L", "M", "N") or ch in ("-", "_"):
            result.append(ch)
        else:
            result.append("_")
    clean = "".join(result)
    clean = re.sub(r"_+", "_", clean).strip("_")
    return clean[:max_length].rstrip("_-")


def find_figure_caption(
    blocks: List[Dict[str, Any]],
    figure_index: int,
    figure_bbox: List[float],
    page_height: float,
    page_width: Optional[float] = None,
    max_lookahead: int = 3,
) -> Optional[str]:
    """
    Find caption/figure name for a figure block.
    Checks:
    1. Figure block itself (e.g. block['caption'], block['figure_name'], block['title'])
    2. Subsequent blocks positioned directly below the figure:
       - Type 'caption', 'figure_caption', 'fig_caption'
       - Or type 'paragraph'/'text' located immediately below the bottom edge of the figure
    """
    if not blocks or figure_index < 0 or figure_index >= len(blocks):
        return None

    fig_block = blocks[figure_index]
    # Check if figure block itself has metadata
    for key in ("caption", "figure_name", "title", "label_text", "fig_name"):
        val = fig_block.get(key)
        if val and isinstance(val, str) and val.strip():
            return val.strip()

    if not figure_bbox or len(figure_bbox) != 4:
        return None

    try:
        f_xmin, f_ymin, f_xmax, f_ymax = map(float, figure_bbox)
    except (ValueError, TypeError):
        return None

    page_h = float(page_height or 1000.0)
    # Maximum vertical distance from bottom of figure to top of caption
    max_gap_px = max(40.0, 0.08 * page_h)

    caption_types = {"caption", "figure_caption", "fig_caption"}

    # Look ahead in subsequent blocks (reading order)
    for offset in range(1, max_lookahead + 1):
        idx = figure_index + offset
        if idx >= len(blocks):
            break
        cand = blocks[idx]
        ctype = str(
            cand.get("type") or cand.get("category") or cand.get("label") or ""
        ).lower()

        # If another visual figure element is encountered, stop
        if ctype in DEFAULT_IMAGE_TYPES:
            break

        cand_bbox = cand.get("bbox")
        raw_text = cand.get("content") or cand.get("text") or ""
        from bs4 import BeautifulSoup

        text = (
            BeautifulSoup(raw_text, "html.parser").get_text().strip()
            if raw_text
            else ""
        )
        if not text:
            continue

        # If explicitly marked as caption type
        if ctype in caption_types:
            return text

        # If spatial coordinates are present, check position below the figure
        if cand_bbox and len(cand_bbox) == 4:
            try:
                c_xmin, c_ymin, c_xmax, c_ymax = map(float, cand_bbox)
            except (ValueError, TypeError):
                continue

            vertical_dist = c_ymin - f_ymax
            if -15.0 <= vertical_dist <= max_gap_px:
                # Check horizontal alignment/overlap
                overlap_x = min(f_xmax, c_xmax) - max(f_xmin, c_xmin)
                if overlap_x > -50.0:
                    # If it starts with common figure prefixes
                    if re.match(
                        r"^(fig|figure|plate|illustration|diagram|chart|map|चित्र|படம்|படம்\.|रेखाचित्र|आकृति)\b",
                        text,
                        re.IGNORECASE,
                    ):
                        return text
                    # Or if it's the very next block and concise (< 180 chars)
                    if offset == 1 and len(text) <= 180:
                        return text

    return None


def save_crop_to_storage(
    cropped_img: Image.Image,
    block_id: Any,
    project_slug: Optional[str] = None,
    output_dir: Optional[str] = None,
    file_prefix: Optional[str] = None,
    figure_name: Optional[str] = None,
) -> str:
    """
    Save the cropped image either to the application's Storage backend (if project_slug is provided)
    or to a local directory. Returns the path or key where it was saved.
    When figure_name is supplied, generates `{actualFigName}-{uuid}.png`.
    """
    filename = None
    if figure_name:
        slug = slugify_figure_name(figure_name)
        if slug:
            storage_uuid = uuid.uuid4().hex[:8]
            filename = f"{slug}-{storage_uuid}.png"

    if not filename:
        if file_prefix:
            clean_prefix = "".join(
                c if c.isalnum() or c in ("-", "_") else "_" for c in str(file_prefix)
            )
            filename = f"extracted_{clean_prefix}_{block_id}.png"
        else:
            filename = f"extracted_{block_id}.png"

    if project_slug:
        try:
            from kalanjiyam.utils.storage import editor_image_key, get_storage

            # Save to in-memory byte array
            img_byte_arr = io.BytesIO()
            cropped_img.save(img_byte_arr, format="PNG")
            img_byte_arr.seek(0)

            # Store in application storage
            storage = get_storage()
            key = editor_image_key(project_slug, filename)
            storage.save(key, img_byte_arr)

            # Update storage usage log
            try:
                from kalanjiyam.utils.storage import add_storage_usage_for_project

                add_storage_usage_for_project(project_slug)
            except Exception:
                pass

            logger.info(f"Saved cropped block {block_id} to storage key: {key}")
            return f"/static/uploads/{project_slug}/images/{filename}"
        except Exception as e:
            logger.exception(f"Failed to save crop {block_id} to Storage backend: {e}")

    # Fallback to local filesystem saving
    if not output_dir:
        output_dir = "extracted_elements"

    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, filename)
    cropped_img.save(output_path, "PNG")
    logger.info(f"Saved cropped block {block_id} locally to: {output_path}")
    return output_path


def crop_elements_from_image(
    image_path: str,
    layout_data: Dict[str, Any],
    project_slug: Optional[str] = None,
    output_dir: Optional[str] = None,
    image_types: set = DEFAULT_IMAGE_TYPES,
    file_prefix: Optional[str] = None,
    use_caption_naming: bool = False,
) -> List[str]:
    """
    Scale the source image to match layout coordinates and crop identified visual elements.
    Updates layout_data block content to contain the img tag referencing the cropped image.
    Preserves visual block types (figure, image, etc.) without mutating them to paragraph.
    """
    if isinstance(layout_data, list):
        layout_data = {"blocks": layout_data}

    page_width = layout_data.get("page_width")
    page_height = layout_data.get("page_height")

    if not os.path.exists(image_path):
        logger.warning(f"Source image not found: {image_path}. Skipping crop.")
        return []

    if not page_width or not page_height:
        try:
            with Image.open(image_path) as _im:
                page_width, page_height = _im.size
                layout_data["page_width"] = page_width
                layout_data["page_height"] = page_height
        except Exception as e:
            logger.warning(
                "Could not determine page dimensions from image %s: %s",
                image_path,
                e,
            )
            return []

    if not file_prefix and image_path:
        from pathlib import Path

        file_prefix = Path(image_path).stem

    try:
        with Image.open(image_path) as img:
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")

            scaled_img = img.resize((page_width, page_height), Image.Resampling.LANCZOS)

            saved_paths = []
            blocks = layout_data.get("blocks", []) or []
            for block_index, block in enumerate(blocks):
                block_type = str(
                    block.get("type")
                    or block.get("category")
                    or block.get("label")
                    or ""
                ).lower()
                block_id = block.get("id")
                bbox = block.get("bbox")

                if block_type in image_types:
                    if not bbox or len(bbox) != 4:
                        continue
                    if block_id is None:
                        continue

                    xmin, ymin, xmax, ymax = map(float, bbox)

                    xmin = max(0.0, min(xmin, float(page_width)))
                    ymin = max(0.0, min(ymin, float(page_height)))
                    xmax = max(0.0, min(xmax, float(page_width)))
                    ymax = max(0.0, min(ymax, float(page_height)))

                    if xmax <= xmin or ymax <= ymin:
                        continue

                    figure_name = None
                    if use_caption_naming:
                        figure_name = find_figure_caption(
                            blocks=blocks,
                            figure_index=block_index,
                            figure_bbox=bbox,
                            page_height=page_height,
                            page_width=page_width,
                        )

                    cropped = scaled_img.crop(
                        (int(xmin), int(ymin), int(xmax), int(ymax))
                    )
                    saved_path = save_crop_to_storage(
                        cropped,
                        block_id,
                        project_slug=project_slug,
                        output_dir=output_dir,
                        file_prefix=file_prefix,
                        figure_name=figure_name,
                    )
                    saved_paths.append(saved_path)

                    # Update block content to display the image while preserving visual figure type
                    block["content"] = (
                        f'<img class="max-w-full max-h-full h-auto rounded-lg object-contain mx-auto" src="{saved_path}">'
                    )
                    block["image_path"] = saved_path
                    if figure_name:
                        block["figure_name"] = figure_name
                    if block.get("type") not in image_types:
                        block["type"] = "figure"
            return saved_paths
    except Exception as e:
        logger.exception(f"Failed to crop elements from image {image_path}: {e}")
        return []


def crop_elements_from_pdf(
    pdf_path: str,
    layout_data: Dict[str, Any],
    project_slug: Optional[str] = None,
    output_dir: Optional[str] = None,
    page_num: int = 0,
    image_types: set = DEFAULT_IMAGE_TYPES,
    file_prefix: Optional[str] = None,
    use_caption_naming: bool = False,
) -> List[str]:
    """
    Render the PDF page directly at the layout coordinate resolution and crop identified visual elements.
    Updates layout_data block content to contain the img tag referencing the cropped image.
    Preserves visual block types (figure, image, etc.) without mutating them to paragraph.
    """
    if isinstance(layout_data, list):
        layout_data = {"blocks": layout_data}

    page_width = layout_data.get("page_width")
    page_height = layout_data.get("page_height")

    if not os.path.exists(pdf_path):
        logger.warning(f"Source PDF not found: {pdf_path}. Skipping crop.")
        return []

    if not page_width or not page_height:
        try:
            _doc = fitz.open(pdf_path)
            if 0 <= page_num < len(_doc):
                _p = _doc[page_num]
                page_width, page_height = int(_p.rect.width), int(_p.rect.height)
                layout_data["page_width"] = page_width
                layout_data["page_height"] = page_height
            _doc.close()
        except Exception as e:
            logger.warning(
                "Could not determine page dimensions from PDF %s: %s", pdf_path, e
            )
            return []

    if not file_prefix:
        from pathlib import Path

        file_prefix = f"{Path(pdf_path).stem}_p{page_num + 1}"

    try:
        doc = fitz.open(pdf_path)
        if page_num < 0 or page_num >= len(doc):
            logger.warning(
                f"Page index {page_num} is out of bounds for the PDF. Skipping crop."
            )
            doc.close()
            return []

        page = doc[page_num]
        orig_w = page.rect.width
        orig_h = page.rect.height

        zoom_x = page_width / orig_w
        zoom_y = page_height / orig_h
        matrix = fitz.Matrix(zoom_x, zoom_y)

        pix = page.get_pixmap(matrix=matrix)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        saved_paths = []
        blocks = layout_data.get("blocks", []) or []
        for block_index, block in enumerate(blocks):
            block_type = str(
                block.get("type")
                or block.get("category")
                or block.get("label")
                or ""
            ).lower()
            block_id = block.get("id")
            bbox = block.get("bbox")

            if block_type in image_types:
                if not bbox or len(bbox) != 4:
                    continue
                if block_id is None:
                    continue

                xmin, ymin, xmax, ymax = map(float, bbox)

                xmin = max(0.0, min(xmin, float(page_width)))
                ymin = max(0.0, min(ymin, float(page_height)))
                xmax = max(0.0, min(xmax, float(page_width)))
                ymax = max(0.0, min(ymax, float(page_height)))

                if xmax <= xmin or ymax <= ymin:
                    continue

                figure_name = None
                if use_caption_naming:
                    figure_name = find_figure_caption(
                        blocks=blocks,
                        figure_index=block_index,
                        figure_bbox=bbox,
                        page_height=page_height,
                        page_width=page_width,
                    )

                cropped = img.crop((int(xmin), int(ymin), int(xmax), int(ymax)))
                saved_path = save_crop_to_storage(
                    cropped,
                    block_id,
                    project_slug=project_slug,
                    output_dir=output_dir,
                    file_prefix=file_prefix,
                    figure_name=figure_name,
                )
                saved_paths.append(saved_path)

                # Update block content to display the image while preserving visual figure type
                block["content"] = (
                    f'<img class="max-w-full h-auto rounded-lg" src="{saved_path}">'
                )
                block["image_path"] = saved_path
                if figure_name:
                    block["figure_name"] = figure_name
                if block.get("type") not in image_types:
                    block["type"] = "figure"

        doc.close()
        return saved_paths
    except Exception as e:
        logger.exception(f"Failed to crop elements from PDF {pdf_path}: {e}")
        return []


def crop_ocr_response_elements(
    doc_path: str,
    ocr_response: Any,
    project_slug: Optional[str] = None,
    output_dir: Optional[str] = None,
    page_num: int = 0,
    use_caption_naming: bool = False,
) -> List[str]:
    """
    Crop visual elements from OCR response object / dict.
    Updates ocr_response blocks in-place with the proper display img tag.
    """
    if not doc_path or not ocr_response:
        return []

    from pathlib import Path

    file_prefix = Path(doc_path).stem if doc_path else None

    # Get blocks list (it could be a list of dicts or custom objects)
    raw_blocks = getattr(ocr_response, "blocks", []) or []

    # We must support updating in-place. If they are custom objects (like Block class),
    # or dicts, we wrap them in a unified format for croppers.
    blocks_as_dicts = []
    for b in raw_blocks:
        if isinstance(b, dict):
            blocks_as_dicts.append(b)
        else:
            # Assume custom object (Block class)
            blocks_as_dicts.append(
                {
                    "id": getattr(b, "id", None),
                    "type": getattr(b, "type", None),
                    "bbox": getattr(b, "bbox", None),
                    "content": getattr(b, "content", ""),
                    "caption": getattr(b, "caption", None),
                    "figure_name": getattr(b, "figure_name", None),
                }
            )

    layout_data = {
        "page_width": getattr(ocr_response, "page_width", None),
        "page_height": getattr(ocr_response, "page_height", None),
        "blocks": blocks_as_dicts,
    }

    if not layout_data["page_width"] or not layout_data["page_height"]:
        return []

    ext = os.path.splitext(doc_path)[1].lower()
    if ext == ".pdf":
        saved_paths = crop_elements_from_pdf(
            doc_path,
            layout_data,
            project_slug=project_slug,
            output_dir=output_dir,
            page_num=page_num,
            file_prefix=file_prefix,
            use_caption_naming=use_caption_naming,
        )
    else:
        saved_paths = crop_elements_from_image(
            doc_path,
            layout_data,
            project_slug=project_slug,
            output_dir=output_dir,
            file_prefix=file_prefix,
            use_caption_naming=use_caption_naming,
        )

    # Sync content back to the original objects in ocr_response.blocks if they were updated
    for original, updated in zip(raw_blocks, blocks_as_dicts):
        if "content" in updated:
            if isinstance(original, dict):
                original["content"] = updated["content"]
                if "image_path" in updated:
                    original["image_path"] = updated["image_path"]
                if "figure_name" in updated:
                    original["figure_name"] = updated["figure_name"]
                if updated.get("type"):
                    original["type"] = updated["type"]
            else:
                setattr(original, "content", updated["content"])
                if "image_path" in updated:
                    setattr(original, "image_path", updated["image_path"])
                if "figure_name" in updated:
                    setattr(original, "figure_name", updated["figure_name"])
                if updated.get("type"):
                    setattr(original, "type", updated["type"])

    return saved_paths
