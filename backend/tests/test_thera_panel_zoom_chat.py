"""Thera-World tap-to-zoom must not freeze or clip the main chat list."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_zoom_uses_root_navigator_and_disables_selection():
    widget = (REPO / "mobile/lib/widgets/thera_panel_image.dart").read_text()
    assert "SelectionContainer.disabled" in widget
    assert "rootNavigator: true" in widget
    assert "static Future<void> openZoom" in widget
    assert "onZoomClosed" in widget
    assert "onZoomOpened" in widget
    assert widget.count("WebHtmlElementStrategy.fallback") == 2


def test_chat_restores_scroll_after_panel_zoom():
    src = (REPO / "mobile/lib/updated_screens.dart").read_text()
    assert "_restoreChatScrollAfterOverlay" in src
    assert "onZoomClosed: _restoreChatScrollAfterOverlay" in src
    assert "_chatSelectionEpoch" in src
    assert "_chatSelectionIgnoreUntilMs" in src
    assert "ValueKey('chat-select-$_chatSelectionEpoch')" in src
    assert "[THERA_PANEL_IMG]|" in src
    assert "go deeper with you on this panel" in src
    ask = (REPO / "mobile/lib/widgets/thera_go_deeper_ask.dart").read_text()
    assert "theraGoDeeperAsk" in ask
    assert "Skip the usual three journaling prompts" not in ask
    assert "Walk Sense, Image, Feel, Think" in ask
    src = (REPO / "mobile/lib/updated_screens.dart").read_text()
    assert "showTheraPanelLegend" in src
    assert "_recapBtn('Legend'" in src
    legend = (REPO / "mobile/lib/widgets/thera_panel_legend.dart").read_text()
    assert "codex/panel/" in legend
    assert "Sit with the figures with me" not in ask
    vault = (REPO / "mobile/lib/screens/vault_browser_screen.dart").read_text()
    assert "theraGoDeeperAsk(" in vault
    assert vault.count("WebHtmlElementStrategy.fallback") == 2
    assert "_scrollToBottom({bool instant = false})" in src
    assert "_scrollController.jumpTo(pos.maxScrollExtent)" in src


def test_store_image_labels_jpeg_bytes():
    from app.sse.infrastructure.r2_storage import image_content_type
    assert image_content_type(b"\xff\xd8\xff\xe0" + b"\x00" * 8) == "image/jpeg"
    assert image_content_type(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8) == "image/png"
