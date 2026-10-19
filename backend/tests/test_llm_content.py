from app.services.llm import content_text, parse_json_text


def test_content_as_chunks_keeps_text_only():
    """Mistral Large 4 : réflexion et texte en morceaux ; seul le texte est gardé."""
    chunks = [{"type": "thinking", "thinking": [{"type": "text", "text": "je réfléchis"}]},
              {"type": "text", "text": '{"intent": '}, {"type": "text", "text": '"game_help"}'}]
    assert content_text(chunks) == '{"intent": "game_help"}'
    assert parse_json_text(content_text(chunks)) == {"intent": "game_help"}
    assert content_text("déjà du texte") == "déjà du texte" and content_text(None) == ""
