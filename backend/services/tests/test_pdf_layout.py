"""Synthetic layout tests; no private annual-report PDF is required."""

from io import BytesIO

from PIL import Image, ImageDraw

from backend.services.pdf_layout import _left_crop_start, _rotation_from_pdf_lines, _two_up_seam, crop_and_rotate_png, _numbered_spread_regions


def _png(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_detects_wide_two_up_gutter():
    image = Image.new("RGB", (1200, 650), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((70, 100, 580, 550), fill="black")
    draw.rectangle((720, 100, 1140, 550), fill="black")
    seam = _two_up_seam(_png(image))
    assert seam is not None
    assert 0.48 < seam < 0.60


def test_portrait_page_is_not_split():
    assert _two_up_seam(_png(Image.new("RGB", (600, 900), "white"))) is None


def test_green_contents_strip_is_trimmed_without_requiring_rotation():
    image = Image.new("RGB", (1200, 650), "white")
    ImageDraw.Draw(image).rectangle((0, 0, 205, 649), fill=(220, 250, 220))
    assert _left_crop_start(_png(image)) == 0.18


def test_pdf_text_direction_only_selects_rotation():
    class Page:
        def get_text(self, _kind):
            return {"blocks": [{"lines": [{"dir": (0, -1)} for _ in range(12)]}]}

    assert _rotation_from_pdf_lines(Page()) == 270


def test_crop_and_rotate_has_expected_dimensions():
    image = Image.new("RGB", (120, 60), "white")
    output = crop_and_rotate_png(
        _png(image), {"crop_box": [0.0, 0.0, 0.5, 1.0], "rotation": 270},
    )
    with Image.open(BytesIO(output)) as rotated:
        assert rotated.size == (60, 60)


def test_colored_numbered_spread_detected_without_using_evidence_values():
    from types import SimpleNamespace
    class Page:
        rect=SimpleNamespace(width=1440,height=846)
        def get_text(self,_kind):
            return {'blocks':[{'lines':[
                {'bbox':(304,27,350,50),'spans':[{'text':'002 /'}]},
                {'bbox':(913,27,959,50),'spans':[{'text':'003 /'}]}]}]}
    regions=_numbered_spread_regions(Page())
    assert regions and len(regions)==2
    assert .58<regions[0]['crop_box'][2]<.63
    assert regions[0]['crop_box'][2]>regions[1]['crop_box'][0]


def test_table_amounts_or_nonconsecutive_headings_do_not_trigger_spread():
    from types import SimpleNamespace
    class Page:
        rect=SimpleNamespace(width=1440,height=846)
        def get_text(self,_kind):
            return {'blocks':[{'lines':[
                {'bbox':(304,27,350,50),'spans':[{'text':'100'}]},
                {'bbox':(913,27,959,50),'spans':[{'text':'101'}]}]}]}
    assert _numbered_spread_regions(Page()) is None
    original=Page.get_text
    Page.get_text=lambda self,kind:{'blocks':[{'lines':[
        {'bbox':(304,27,350,50),'spans':[{'text':'002 /'}]},
        {'bbox':(913,27,959,50),'spans':[{'text':'005 /'}]}]}]}
    assert _numbered_spread_regions(Page()) is None
