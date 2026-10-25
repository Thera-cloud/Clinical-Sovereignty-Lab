import io

from app.services.chat_vision import bytes_to_vision_data_url, overlap_score, r2_key_from_url


def test_r2_key_from_account_host():
    url = (
        "https://8350b355ec3c721d5f1853e80970d3c1.r2.cloudflarestorage.com/"
        "nate-vault/sse/journey/CLIENT_001/panel.png?X-Amz-Signature=abc"
    )
    assert r2_key_from_url(url) == "sse/journey/CLIENT_001/panel.png"


def test_overlap_open_sky_vs_cloudstone():
    sky = "You stand freely beneath the boundless open sky, your battle-hard Seraph wings"
    cloud = "You cross onto the cloudstone islands where lightning tethers hold the spires"
    same = "You stand freely beneath the boundless open sky, Seraph wings resting at ease"
    assert overlap_score(sky, same) >= 3
    assert overlap_score(sky, cloud) < overlap_score(sky, same)


def test_bytes_to_vision_jpeg_shrinks():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (2400, 1800), color=(12, 80, 160)).save(buf, format="PNG")
    url = bytes_to_vision_data_url(buf.getvalue())
    assert url is not None
    assert url.startswith("data:image/jpeg;base64,")
    raw = url.split(",", 1)[1]
    import base64

    out = base64.b64decode(raw)
    assert 800 < len(out) < 250_000
