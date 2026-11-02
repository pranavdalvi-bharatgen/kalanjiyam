import os
import json
from PIL import Image
import pytest

from kalanjiyam.utils.ocr_cropper import (
    crop_elements_from_image,
    crop_ocr_response_elements,
    DEFAULT_IMAGE_TYPES,
)
from scripts.crop_ocr_elements import process_document


def test_crop_elements_from_image_preserves_figure_type(tmp_path):
    img_path = str(tmp_path / "page.png")
    out_dir = str(tmp_path / "output")
    Image.new("RGB", (200, 300), color="blue").save(img_path)

    layout_data = {
        "page_width": 200,
        "page_height": 300,
        "blocks": [
            {
                "id": "b001",
                "type": "figure",
                "bbox": [10, 20, 80, 90],
                "content": "",
            },
            {
                "id": "b002",
                "type": "paragraph",
                "bbox": [10, 100, 190, 150],
                "content": "Some body text",
            },
        ],
    }

    saved_paths = crop_elements_from_image(
        image_path=img_path,
        layout_data=layout_data,
        project_slug=None,
        output_dir=out_dir,
    )

    assert len(saved_paths) == 1
    assert os.path.exists(saved_paths[0])

    # Crucial regression check: block["type"] must NOT be mutated to "paragraph"
    fig_block = layout_data["blocks"][0]
    assert fig_block["type"] == "figure"
    assert "image_path" in fig_block
    assert fig_block["image_path"] == saved_paths[0]
    assert "<img " in fig_block["content"]


def test_crop_elements_from_image_detects_category_picture(tmp_path):
    img_path = str(tmp_path / "page.png")
    out_dir = str(tmp_path / "output")
    Image.new("RGB", (500, 600), color="green").save(img_path)

    layout_data = {
        "blocks": [
            {
                "id": "pic_01",
                "category": "Picture",
                "bbox": [20, 30, 200, 250],
            }
        ]
    }

    saved_paths = crop_elements_from_image(
        image_path=img_path,
        layout_data=layout_data,
        project_slug=None,
        output_dir=out_dir,
    )

    assert len(saved_paths) == 1
    assert os.path.exists(saved_paths[0])

    pic_block = layout_data["blocks"][0]
    assert pic_block["type"] == "figure"
    assert "<img " in pic_block["content"]


def test_crop_elements_from_image_infers_page_dimensions(tmp_path):
    img_path = str(tmp_path / "page.png")
    out_dir = str(tmp_path / "output")
    Image.new("RGB", (400, 800), color="yellow").save(img_path)

    layout_data = {
        # page_width and page_height intentionally omitted
        "blocks": [
            {
                "id": "fig_01",
                "type": "image",
                "bbox": [10, 10, 390, 400],
            }
        ]
    }

    saved_paths = crop_elements_from_image(
        image_path=img_path,
        layout_data=layout_data,
        project_slug=None,
        output_dir=out_dir,
    )

    assert len(saved_paths) == 1
    assert layout_data["page_width"] == 400
    assert layout_data["page_height"] == 800


def test_crop_ocr_response_elements_syncs_blocks(tmp_path):
    img_path = str(tmp_path / "page.png")
    out_dir = str(tmp_path / "output")
    Image.new("RGB", (300, 400), color="white").save(img_path)

    class MockOcrResponse:
        page_width = 300
        page_height = 400
        blocks = [
            {
                "id": "b1",
                "type": "figure",
                "bbox": [15, 25, 150, 200],
                "content": "",
            }
        ]

    resp = MockOcrResponse()
    paths = crop_ocr_response_elements(
        doc_path=img_path,
        ocr_response=resp,
        project_slug=None,
        output_dir=out_dir,
    )

    assert len(paths) == 1
    assert resp.blocks[0]["type"] == "figure"
    assert "<img " in resp.blocks[0]["content"]
    assert resp.blocks[0]["image_path"] == paths[0]


def test_process_document_standalone_script_without_flask_context(tmp_path):
    img_path = str(tmp_path / "source.png")
    json_path = str(tmp_path / "layout.json")
    out_dir = str(tmp_path / "cropped_out")
    save_json_path = str(tmp_path / "updated_layout.json")

    Image.new("RGB", (300, 400), color="red").save(img_path)
    raw_layout = {
        "page_width": 300,
        "page_height": 400,
        "blocks": [
            {
                "id": "elem_1",
                "type": "figure",
                "bbox": [20, 20, 200, 200],
            }
        ],
    }
    with open(json_path, "w") as f:
        json.dump(raw_layout, f)

    # Calling process_document should succeed locally without RuntimeError: Working outside of application context
    results = process_document(
        doc_path=img_path,
        json_path=json_path,
        output_dir=out_dir,
        project_slug=None,
        save_json_path=save_json_path,
    )

    assert len(results) == 1
    assert os.path.exists(results[0])
    assert os.path.exists(save_json_path)

    with open(save_json_path) as f:
        updated = json.load(f)
    assert updated["blocks"][0]["type"] == "figure"
    assert "<img " in updated["blocks"][0]["content"]
