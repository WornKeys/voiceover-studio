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
