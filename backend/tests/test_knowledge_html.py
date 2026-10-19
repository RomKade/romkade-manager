from app.services.knowledge import chunk_extract, html_text


def test_html_text_keeps_tables_lists_and_button_images():
    """Sega Retro : objets en tableau, boutons en images ; références, sommaire et liens d'édition retirés."""
    html = """<div class="toc">Contents 1 Story</div>
    <h2>Items<span class="mw-editsection">[edit]</span></h2>
    <table><tr><th>Telepathy Ball</th><td>Shows what Janken is thinking.<sup class="reference">[1]</sup></td></tr>
    <tr><th>Power Bracelet</th><td>Fires a shock wave.</td></tr></table>
    <h2>Continue mode</h2><p>On the Game Over screen, press HOLD <img alt="Up" src="u.png"> <img alt="2" src="b.png"> x8.</p>
    <h2>References</h2><ol><li>Manual, p. 3</li></ol>"""
    text = html_text(html)
    assert "== Items ==" in text and "Telepathy Ball · Shows what Janken is thinking." in text
    assert "press HOLD Up 2 x8." in text and "[1]" not in text and "Contents" not in text and "edit" not in text
    sections = dict(chunk_extract(text + "\n" + "word " * 20, "Alex Kidd"))
    assert "Items" in sections and "References" not in sections
