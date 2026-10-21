import pytest

from habermk.validate import (
    LLMFormatError, check, count_graphemes, first_word_warning, parse_llm_json,
    sentence_errors, unsupported_facts,
)

ARTICLE = (
    "Министерството за внатрешни работи соопшти дека полицијата во Скопје пронашла две "
    "автоматски пушки и над 500 парчиња муниција. Според МВР, осомничениот Б.А. (24) е "
    "член на ИСИС и врбувал млади лица. Обвинителството ќе побара притвор од 30 дена."
)
GOOD = {
    "status": "OK",
    "sentence": "Полицијата во Скопје пронашла пушки и над 500 парчиња муниција кај Б.А. (24), "
                "кој според МВР е член на ИСИС.",
    "evidence": "Според МВР, осомничениот Б.А. (24) е член на ИСИС и врбувал млади лица.",
    "scope": "MK",
    "reason": "",
}
CFG = {"max_sentence_chars": 220, "min_cyrillic_ratio": 0.9, "min_evidence_chars": 20}


def errs(s):
    return sentence_errors(s, 220, 0.9)


def test_good_answer_passes():
    assert check(GOOD, ARTICLE, CFG) == []


def test_skip_is_never_ok():
    assert check({**GOOD, "status": "SKIP"}, ARTICLE, CFG)


@pytest.mark.parametrize("sentence,problem", [
    ("Владата донесе одлука. Министерот се согласи.", "more than one sentence"),
    ("Владата донесе одлука", "does not end"),
    ("Дали Владата донесе одлука?", "question mark"),
    ("Оваа вест открива дека Владата донесе одлука.", "banned intro"),
    ("Според статијата, Владата донесе одлука.", "banned intro"),
    ("Веста: Владата донесе одлука.", "banned intro"),
    ("The government made a decision today in Skopje.", "Cyrillic"),
    ("Владата донесе одлука 🔥.", "emoji"),
    ("Владата донесе одлука #вести.", "hashtag"),
    ("Владата " + "донесе " * 40 + "одлука.", "too long"),
    ("", "empty"),
])
def test_format_rules(sentence, problem):
    assert any(problem in e for e in errs(sentence)), errs(sentence)


@pytest.mark.parametrize("sentence", [
    "Уапсен е Б.А. од Скопје, соопшти МВР.",           # initials are not a sentence end
    "Д-р. Петровски е новиот директор на болницата.",
    "Цената на лебот расте за 5 ден. од понеделник.",   # abbreviation
    "Американската технолошка компанија Microsoft ќе отвори нова регионална канцеларија "
    "во Скопје со педесет вработени.",  # some Latin is fine
])
def test_valid_sentences(sentence):
    assert errs(sentence) == []


def test_evidence_must_be_verbatim():
    bad = {**GOOD, "evidence": "Според МВР, осомничениот е член на Ал Каида."}
    assert "evidence not found verbatim in article" in check(bad, ARTICLE, CFG)


def test_evidence_matches_despite_quote_and_space_differences():
    art = ARTICLE.replace("Според МВР,", "Според  „МВР“,")
    ev = {**GOOD, "evidence": 'Според "МВР", осомничениот Б.А. (24) е член на ИСИС'}
    assert check(ev, art, CFG) == []


def test_invented_number_is_rejected():
    bad = {**GOOD, "sentence": GOOD["sentence"].replace("500", "700")}
    assert any("numbers not in article" in e for e in check(bad, ARTICLE, CFG))


def test_invented_name_is_rejected():
    s = "Полицијата во Куманово пронашла пушки кај Б.А. (24), според МВР."
    assert any("Куманово" in e for e in unsupported_facts(s, ARTICLE))


def test_inflected_name_is_accepted():
    s = "Над 500 парчиња муниција се пронајдени кај млад човек, според МВР, а Скопјани се загрижени."
    assert unsupported_facts(s, ARTICLE) == []


def test_world_news_is_out_of_scope():
    assert "world news (out of scope)" in check({**GOOD, "scope": "WORLD"}, ARTICLE, CFG)


def test_first_word_warning():
    assert first_word_warning("Пронајдени се пушки.", ARTICLE) is not None
    assert first_word_warning("Полицијата пронашла пушки.", ARTICLE) is None


def test_parse_llm_json_tolerates_fences_and_think():
    raw = '<think>hmm</think>```json\n{"status":"OK","sentence":" А. ","evidence":"x"}\n```'
    data = parse_llm_json(raw)
    assert data["sentence"] == "А." and data["scope"] == ""


@pytest.mark.parametrize("raw", ["", "no json", '{"status":"MAYBE"}', "{bad json}"])
def test_parse_llm_json_rejects_garbage(raw):
    with pytest.raises(LLMFormatError):
        parse_llm_json(raw)


def test_count_graphemes():
    assert count_graphemes("Ѓорѓи") == 5
