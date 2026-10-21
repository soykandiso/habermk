from habermk.formatting import bluesky_text, facebook_text, platform_errors, telegram_text

S = "Владата ја зголеми минималната плата на 24.000 денари од јануари."


def test_source_is_always_named():
    assert telegram_text(S, "СДК", "https://sdk.mk/a").endswith("— СДК: https://sdk.mk/a")
    assert bluesky_text(S, "СДК").endswith("— СДК")
    assert facebook_text(S, "СДК").endswith("— СДК")


def test_bluesky_limit(cfg):
    assert platform_errors(S, "СДК", "https://sdk.mk/a", cfg["platforms"]) == []
    long = "А" * 296 + "."
    errors = platform_errors(long, "СДК", "https://sdk.mk/a", cfg["platforms"])
    assert errors and "Bluesky" in errors[0]


def test_max_sentence_always_fits_bluesky(cfg):
    """A sentence at the validation limit plus a long outlet name still fits."""
    sentence = "А" * (cfg["validation"]["max_sentence_chars"] - 1) + "."
    assert platform_errors(sentence, "Македонска информативна агенција", "https://mia.mk/x",
                           cfg["platforms"]) == []
