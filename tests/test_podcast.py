from briefing.podcast import PODCAST_MINUTES, SAMPLE_PATH, build_message, speech_text


def test_speech_text_removes_markup_and_says_symbols():
    out = speech_text("## Titolo\n- **Brent** a 110$ (+3%) [FT](https://ft.com)\n\n\n"
                      "Vedi https://x.y/z e `codice` > citazione")
    assert out == "Titolo\nBrent a 110 dollari, +3 per cento, FT\n\nVedi e codice citazione"


def test_message_asks_for_length_matching_minutes():
    msg = build_message("## Italy\nNews", "sabato 7 novembre 2026", PODCAST_MINUTES["saturday"])
    assert "about 4250 words" in msg and "about 25 minutes" in msg and "## Italy" in msg


def test_sample_script_is_plain_italian():
    text = SAMPLE_PATH.read_text()
    assert "Buongiorno" in text and speech_text(text).count("\n\n") >= 8
