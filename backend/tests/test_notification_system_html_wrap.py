"""Bug #3 (double-wrapped digest HTML): callers that already built a
complete, self-styled HTML block must be able to skip the "Little Nate /
AI Therapy Companion" purple template wrapper entirely.
"""
from app.websocket.notification_system import NotificationSystem


def test_minimal_html_wrap_has_no_therapy_companion_branding(tmp_path):
    ns = NotificationSystem(data_dir=tmp_path, sendgrid_key=None)
    digest_html = '<div style="color:#C9A962;">Sovereign Sanctuary — Trial Digest</div>'
    wrapped = ns._minimal_html_wrap(digest_html)

    assert "AI Therapy Companion" not in wrapped
    assert "Little Nate" not in wrapped
    assert digest_html in wrapped
    assert wrapped.count("<html>") == 1
    assert wrapped.count("<body") == 1


def test_minimal_html_wrap_does_not_mangle_multiline_style_attrs(tmp_path):
    # The old _format_email_html path rewrote bare `\n` to `<br>`, which
    # broke multi-line style="..." attributes in pre-built HTML (the exact
    # "styles concatenated into one broken line" symptom reported).
    ns = NotificationSystem(data_dir=tmp_path, sendgrid_key=None)
    digest_html = (
        '<div style="font-family:\'DM Sans\',Arial,sans-serif;max-width:640px;'
        'margin:0 auto;background:#0A0A0A;">content</div>'
    )
    wrapped = ns._minimal_html_wrap(digest_html)
    assert digest_html in wrapped
    assert "<br>" not in wrapped
