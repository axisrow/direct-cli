"""
Dynamic tracking parameters reference for Yandex Direct.

Yandex calls these "динамические параметры" (dynamic parameters) — placeholder
variables like ``{campaign_id}`` or ``{keyword}`` that Yandex substitutes into an
ad's URL (including UTM tags) at click time. Used in ``--tracking-params`` for
``campaigns``/``adgroups`` and in ``--sitelink`` hrefs.

The docs URL is declared here once (the registry point for the url-tags page),
mirroring how ``reports_coverage.py`` declares the ``spec`` URL outside the
vendored resource mapping. ``scripts/check_all_docs_urls.py`` imports it so the
release preflight health-checks this URL too. Keep it as the single literal —
see CLAUDE.md "No URL literals outside the registry".
"""

# Yandex help page for tracking parameters — single literal (url-tags registry point).
TRACKING_PARAMS_DOCS_URL = "https://yandex.ru/support/direct/statistics/url-tags.html"

# Each entry: placeholder name, human description, possible values.
TRACKING_PARAMS = [
    {
        "Parameter": "{campaign_id}",
        "Description": "Идентификатор кампании",
        "Values": "число",
    },
    {
        "Parameter": "{campaign_name}",
        "Description": "Название кампании",
        "Values": "текст",
    },
    {
        "Parameter": "{campaign_name_lat}",
        "Description": "Название кампании в транслите",
        "Values": "текст",
    },
    {
        "Parameter": "{campaign_type}",
        "Description": "Тип кампании",
        "Values": "type1..type6",
    },
    {
        "Parameter": "{ad_id} / {banner_id}",
        "Description": "Идентификатор объявления",
        "Values": "число",
    },
    {
        "Parameter": "{creative_id}",
        "Description": "Идентификатор креатива из конструктора",
        "Values": "число",
    },
    {
        "Parameter": "{device_type}",
        "Description": "Тип устройства",
        "Values": "desktop, mobile, tablet",
    },
    {
        "Parameter": "{gbid}",
        "Description": "Идентификатор группы объявлений",
        "Values": "число",
    },
    {
        "Parameter": "{keyword}",
        "Description": "Ключевая фраза, по которой показано объявление",
        "Values": "текст",
    },
    {
        "Parameter": "{phrase_id}",
        "Description": "Идентификатор ключевой фразы",
        "Values": "число",
    },
    {
        "Parameter": "{matched_keyword}",
        "Description": "Подобранная (фактическая) фраза",
        "Values": "текст",
    },
    {
        "Parameter": "{match_type}",
        "Description": "Тип соответствия фразы",
        "Values": "rm, syn",
    },
    {
        "Parameter": "{retargeting_id}",
        "Description": "Идентификатор условия нацеливания на аудиторию",
        "Values": "число",
    },
    {
        "Parameter": "{adtarget_id}",
        "Description": "Идентификатор условия нацеливания (динам./смарт)",
        "Values": "число",
    },
    {
        "Parameter": "{position}",
        "Description": "Точная позиция объявления в блоке",
        "Values": "число; 0 — сети",
    },
    {
        "Parameter": "{position_type}",
        "Description": "Тип блока размещения",
        "Values": "premium, dynamic_places, other, none",
    },
    {
        "Parameter": "{source}",
        "Description": "Место показа (домен площадки в сетях)",
        "Values": "текст/домен",
    },
    {
        "Parameter": "{source_type}",
        "Description": "Тип площадки",
        "Values": "search, context",
    },
    {"Parameter": "{region_name}", "Description": "Регион показа", "Values": "текст"},
    {
        "Parameter": "{region_id}",
        "Description": "Идентификатор региона",
        "Values": "число",
    },
    {
        "Parameter": "{yclid}",
        "Description": "Идентификатор клика (связка с Метрикой)",
        "Values": "число",
    },
]
