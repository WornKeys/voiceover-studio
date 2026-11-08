from voiceover_studio.core.text import chunk_text, estimate_seconds, split_sentences, target_words, word_count


def test_split_sentences_handles_abbreviations_decimals_and_quotes():
    text = 'Dr. Rao measured 3.5 litres. It worked! "Really?" she asked. See e.g. the docs.'
    assert split_sentences(text) == [
        "Dr. Rao measured 3.5 litres.",
        "It worked!",
        '"Really?"',
        "she asked.",
        "See e.g. the docs.",
    ]


def test_blank_lines_end_a_sentence():
    assert split_sentences("Welcome to the course\n\nLet's begin.") == [
        "Welcome to the course",
        "Let's begin.",
    ]


def test_long_sentence_is_split_at_clause_breaks_then_words():
    long = "First we install the tools, then we configure the account, and finally we deploy the app to AWS."
    chunks = chunk_text(long, 40)
    assert all(len(c) <= 40 for c in chunks)
    assert " ".join(chunks) == long


def test_unbreakable_word_is_hard_split():
    chunks = chunk_text("Visit " + "x" * 50 + " today.", 20)
    assert all(len(c) <= 20 for c in chunks)


def test_word_count_and_duration():
    assert word_count("It's a well-known, open-weight model.") == 5
    assert estimate_seconds("one two three four five", 150) == 2.0
    assert target_words(60, 150) == 150


def test_typographic_apostrophes_quotes_and_dashes():
    apostrophe, close_quote, em_dash = chr(0x2019), chr(0x201D), chr(0x2014)
    assert word_count(f"It{apostrophe}s ready") == 2
    text = f"She said {chr(0x201C)}done.{close_quote} Then we ship."
    assert split_sentences(text) == [f"She said {chr(0x201C)}done.{close_quote}", "Then we ship."]
    chunks = chunk_text(f"We record the voice{em_dash} then we write the script and render it.", 30)
    assert chunks[0] == f"We record the voice{em_dash}"


# Chinese/Japanese stand-ins: ideographs and full-width punctuation, written without spaces.
ONE, TWO, THREE = chr(0x4E00), chr(0x4E8C), chr(0x4E09)
FULL_STOP, BANG, QUESTION, COMMA = chr(0x3002), chr(0xFF01), chr(0xFF1F), chr(0xFF0C)


def test_cjk_sentences_end_without_a_space():
    s1, s2, s3 = ONE * 8 + FULL_STOP, TWO * 5 + BANG, THREE * 6 + QUESTION
    assert split_sentences(s1 + s2 + s3) == [s1, s2, s3]
    assert split_sentences("It works. " + s1) == ["It works.", s1]


def test_cjk_long_sentence_splits_at_full_width_commas_without_adding_spaces():
    sentence = (ONE * 10 + COMMA) * 3 + TWO * 5 + FULL_STOP
    chunks = chunk_text(sentence, 25)
    assert all(len(c) <= 25 for c in chunks) and len(chunks) == 2
    assert "".join(chunks) == sentence


def test_cjk_characters_count_as_half_a_word():
    assert word_count(ONE * 10) == 5
    assert word_count("AWS " + ONE * 4 + FULL_STOP) == 3
