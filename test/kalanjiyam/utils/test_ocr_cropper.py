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


def test_slugify_figure_name():
    from kalanjiyam.utils.ocr_cropper import slugify_figure_name

    assert slugify_figure_name("Fig. 1: Ancient Temple") == "Fig_1_Ancient_Temple"
    assert slugify_figure_name("<p>Figure 2 — Map</p>") == "Figure_2_Map"
    assert slugify_figure_name("चित्र १: सरस्वती देवी") == "चित्र_१_सरस्वती_देवी"
    assert slugify_figure_name("படம் 1: கோயில்") == "படம்_1_கோயில்"
    assert slugify_figure_name("") == ""
    assert slugify_figure_name(None) == ""


def test_find_figure_caption_explicit_and_adjacent():
    from kalanjiyam.utils.ocr_cropper import find_figure_caption

    blocks = [
        {
            "id": "b1",
            "type": "figure",
            "bbox": [50, 50, 400, 300],
            "content": "",
        },
        {
            "id": "b2",
            "type": "caption",
            "bbox": [50, 310, 400, 335],
            "content": "Figure 1: Traditional Inscription",
        },
        {
            "id": "b3",
            "type": "paragraph",
            "bbox": [50, 360, 400, 500],
            "content": "Normal text body starts here.",
        },
    ]

    # Test explicit caption block
    cap = find_figure_caption(
        blocks=blocks,
        figure_index=0,
        figure_bbox=[50, 50, 400, 300],
        page_height=1000,
    )
    assert cap == "Figure 1: Traditional Inscription"

    # Test adjacent paragraph with figure prefix when type is paragraph
    blocks_para = [
        {
            "id": "b1",
            "type": "figure",
            "bbox": [50, 50, 400, 300],
            "content": "",
        },
        {
            "id": "b2",
            "type": "paragraph",
            "bbox": [50, 305, 400, 330],
            "content": "Fig. 2 - Architectural Plan",
        },
    ]
    cap_para = find_figure_caption(
        blocks=blocks_para,
        figure_index=0,
        figure_bbox=[50, 50, 400, 300],
        page_height=1000,
    )
    assert cap_para == "Fig. 2 - Architectural Plan"


def test_save_crop_to_storage_uses_actual_fig_name_and_uuid(tmp_path):
    from kalanjiyam.utils.ocr_cropper import save_crop_to_storage
    import re

    img = Image.new("RGB", (50, 50), color="red")
    out_dir = str(tmp_path / "crops")

    # With figure_name
    saved_path = save_crop_to_storage(
        cropped_img=img,
        block_id="b01",
        output_dir=out_dir,
        file_prefix="test_prefix",
        figure_name="Figure 1: Temple Map",
    )
    filename = os.path.basename(saved_path)
    # Pattern: {actualFigName}-{uuid}.png
    assert filename.startswith("Figure_1_Temple_Map-")
    assert filename.endswith(".png")
    # UUID check (8 hex characters)
    match = re.match(r"^Figure_1_Temple_Map-[0-9a-f]{8}\.png$", filename)
    assert match is not None

    # Without figure_name (fallback)
    fallback_path = save_crop_to_storage(
        cropped_img=img,
        block_id="b01",
        output_dir=out_dir,
        file_prefix="p01",
        figure_name=None,
    )
    fallback_name = os.path.basename(fallback_path)
    assert fallback_name == "extracted_p01_b01.png"


def test_crop_elements_from_image_with_caption_naming(tmp_path):
    img_path = str(tmp_path / "page_with_fig.png")
    out_dir = str(tmp_path / "output_crops")
    Image.new("RGB", (500, 700), color="purple").save(img_path)

    layout_data = {
        "page_width": 500,
        "page_height": 700,
        "blocks": [
            {
                "id": "fig_101",
                "type": "figure",
                "bbox": [30, 40, 450, 350],
                "content": "",
            },
            {
                "id": "cap_102",
                "type": "caption",
                "bbox": [30, 360, 450, 390],
                "content": "Figure 4: Bronze Sculpture",
            },
        ],
    }

    # Enabled caption naming
    saved_paths = crop_elements_from_image(
        image_path=img_path,
        layout_data=layout_data,
        project_slug=None,
        output_dir=out_dir,
        use_caption_naming=True,
    )

    assert len(saved_paths) == 1
    assert os.path.exists(saved_paths[0])
    base_name = os.path.basename(saved_paths[0])
    assert base_name.startswith("Figure_4_Bronze_Sculpture-")
    assert layout_data["blocks"][0].get("figure_name") == "Figure 4: Bronze Sculpture"


def test_crop_ocr_response_elements_infers_page_dimensions_when_none(tmp_path):
    img_path = str(tmp_path / "page_chandra.png")
    out_dir = str(tmp_path / "output_crops")
    Image.new("RGB", (600, 800), color="blue").save(img_path)

    class MockOcrResponse:
        page_width = None
        page_height = None
        blocks = [
            {
                "id": "b001",
                "type": "figure",
                "bbox": [60, 80, 540, 500],
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
    assert os.path.exists(paths[0])
    assert resp.page_width == 600
    assert resp.page_height == 800
    assert "<img " in resp.blocks[0]["content"]


def test_crop_elements_from_image_chandra_embedded_caption(tmp_path):
    img_path = str(tmp_path / "page_embedded.png")
    out_dir = str(tmp_path / "output_crops")
    Image.new("RGB", (400, 600), color="red").save(img_path)

    layout_data = {
        "page_width": 400,
        "page_height": 600,
        "blocks": [
            {
                "id": "b001",
                "type": "figure",
                "bbox": [20, 20, 380, 400],
                "content": "Figure 12: Historical Inscription",
            }
        ],
    }
    saved_paths = crop_elements_from_image(
        image_path=img_path,
        layout_data=layout_data,
        project_slug=None,
        output_dir=out_dir,
        use_caption_naming=True,
    )
    assert len(saved_paths) == 1
    assert os.path.exists(saved_paths[0])
    filename = os.path.basename(saved_paths[0])
    assert filename.startswith("Figure_12_Historical_Inscription-")


def test_crop_elements_from_image_normalized_0_to_1_coords(tmp_path):
    img_path = str(tmp_path / "page_norm.png")
    out_dir = str(tmp_path / "output_crops")
    Image.new("RGB", (500, 1000), color="white").save(img_path)

    layout_data = {
        "page_width": 500,
        "page_height": 1000,
        "blocks": [
            {
                "id": "b001",
                "type": "figure",
                "bbox": [0.1, 0.2, 0.8, 0.7],
                "content": "",
            }
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
    with Image.open(saved_paths[0]) as cropped_im:
        # Expected width: (0.8 - 0.1) * 500 = 350
        # Expected height: (0.7 - 0.2) * 1000 = 500
        assert cropped_im.size == (350, 500)


