
RESOURCE_MAPPING_V5 = {
    "adextensions": {
        "resource": "json/v5/adextensions",
        "docs": "https://yandex.ru/dev/direct/doc/ru/adextensions/adextensions",
        "methods": ["get", "add", "delete"],
    },
    "adgroups": {
        "resource": "json/v5/adgroups",
        "docs": "https://yandex.ru/dev/direct/doc/ru/adgroups/adgroups",
        "methods": ["get", "add", "update", "delete"],
    },
    "adimages": {
        "resource": "json/v5/adimages",
        "docs": "https://yandex.ru/dev/direct/doc/ru/adimages/adimages",
        "methods": ["get", "add", "delete"],
    },
    "advideos": {
        "resource": "json/v5/advideos",
        "docs": "https://yandex.ru/dev/direct/doc/ru/advideos/advideos",
        "methods": ["get", "add"],
    },
    "ads": {
        "resource": "json/v5/ads",
        "docs": "https://yandex.ru/dev/direct/doc/ru/ads/ads",
        "methods": ["get", "add", "update", "delete", "moderate", "suspend", "resume", "archive", "unarchive"],
    },
    "agencyclients": {
        "resource": "json/v5/agencyclients",
        "docs": "https://yandex.ru/dev/direct/doc/ru/agencyclients/agencyclients",
        "methods": ["get", "add", "update", "addPassportOrganization", "addPassportOrganizationMember"],
    },
    "audiencetargets": {
        "resource": "json/v5/audiencetargets",
        "docs": "https://yandex.ru/dev/direct/doc/ru/audiencetargets/audiencetargets",
        "methods": ["get", "add", "delete", "suspend", "resume", "setBids"],
    },
    "bids": {
        "resource": "json/v5/bids",
        "docs": "https://yandex.ru/dev/direct/doc/ru/bids/bids",
        "methods": ["get", "set", "setAuto"],
    },
    "bidmodifiers": {
        "resource": "json/v5/bidmodifiers",
        "docs": "https://yandex.ru/dev/direct/doc/ru/bidmodifiers/bidmodifiers",
        "methods": ["get", "add", "set", "delete"],
    },
    "campaigns": {
        "resource": "json/v5/campaigns",
        "docs": "https://yandex.ru/dev/direct/doc/ru/campaigns/campaigns",
        "methods": ["get", "add", "update", "delete", "archive", "unarchive", "suspend", "resume"],
    },
    "changes": {
        "resource": "json/v5/changes",
        "docs": "https://yandex.ru/dev/direct/doc/ru/changes/changes",
        "methods": ["check", "checkCampaigns", "checkDictionaries"],
    },
    "clients": {
        "resource": "json/v5/clients",
        "docs": "https://yandex.ru/dev/direct/doc/ru/clients/clients",
        "methods": ["get", "update"],
    },
    "creatives": {
        "resource": "json/v5/creatives",
        "docs": "https://yandex.ru/dev/direct/doc/ru/creatives/creatives",
        "methods": ["get", "add"],
    },
    "dictionaries": {
        "resource": "json/v5/dictionaries",
        "docs": "https://yandex.ru/dev/direct/doc/ru/dictionaries/dictionaries",
        "methods": ["get"],
    },
    "dynamicads": {
        "resource": "json/v5/dynamictextadtargets",
        "docs": "https://yandex.ru/dev/direct/doc/ru/dynamictextadtargets/dynamictextadtargets",
        "methods": ["get", "add", "delete", "suspend", "resume", "setBids"],
    },
    "dynamicfeedadtargets": {
        "resource": "json/v5/dynamicfeedadtargets",
        "docs": "https://yandex.ru/dev/direct/doc/ru/dynamicfeedadtargets/dynamicfeedadtargets",
        "methods": ["get", "add", "delete", "suspend", "resume", "setBids"],
    },
    "keywordbids": {
        "resource": "json/v5/keywordbids",
        "docs": "https://yandex.ru/dev/direct/doc/ru/keywordbids/keywordbids",
        "methods": ["get", "set", "setAuto"],
    },
    "keywords": {
        "resource": "json/v5/keywords",
        "docs": "https://yandex.ru/dev/direct/doc/ru/keywords/keywords",
        "methods": ["get", "add", "update", "delete", "suspend", "resume"],
    },
    "keywordsresearch": {
        "resource": "json/v5/keywordsresearch",
        "docs": "https://yandex.ru/dev/direct/doc/ru/keywordsresearch/keywordsresearch",
        "methods": ["deduplicate", "hasSearchVolume"],
    },
    "leads": {
        "resource": "json/v5/leads",
        "docs": "https://yandex.ru/dev/direct/doc/ru/leads/leads",
        "methods": ["get"],
    },
    "retargeting": {
        "resource": "json/v5/retargetinglists",
        "docs": "https://yandex.ru/dev/direct/doc/ru/retargetinglists/retargetinglists",
        "methods": ["get", "add", "update", "delete"],
    },
    "sitelinks": {
        "resource": "json/v5/sitelinks",
        "docs": "https://yandex.ru/dev/direct/doc/ru/sitelinks/sitelinks",
        "methods": ["get", "add", "delete"],
    },
    "vcards": {
        "resource": "json/v5/vcards",
        "docs": "https://yandex.ru/dev/direct/doc/ru/vcards/vcards",
        "methods": ["get", "add", "delete"],
    },
    "turbopages": {
        "resource": "json/v5/turbopages",
        "docs": "https://yandex.ru/dev/direct/doc/ru/turbopages/turbopages",
        "methods": ["get"],
    },
    "negativekeywordsharedsets": {
        "resource": "json/v5/negativekeywordsharedsets",
        "docs": "https://yandex.ru/dev/direct/doc/ru/negativekeywordsharedsets/negativekeywordsharedsets",
        "methods": ["get", "add", "update", "delete"],
    },
    "reports": {
        "resource": "json/v5/reports",
        "docs": "https://yandex.ru/dev/direct/doc/ru/reports/reports",
        "methods": ["get"],
        "docs_pages": {
            "type": "https://yandex.ru/dev/direct/doc/ru/reports/type",
            "period": "https://yandex.ru/dev/direct/doc/ru/reports/period",
            "fields-list": "https://yandex.ru/dev/direct/doc/ru/reports/fields-list",
            "headers": "https://yandex.ru/dev/direct/doc/ru/headers",
        },
    },
    "debugtoken": {
        "resource": "oauth.yandex.ru/authorize?response_type=token&client_id={client_id}",
        "docs": "https://yandex.ru/dev/direct/doc/ru/concepts/auth-token",
        "methods": [],
    },
    "feeds": {
        "resource": "json/v5/feeds",
        "docs": "https://yandex.ru/dev/direct/doc/ru/feeds/feeds",
        "methods": ["get", "add", "update", "delete"],
    },
    "smartadtargets": {
        "resource": "json/v5/smartadtargets",
        "docs": "https://yandex.ru/dev/direct/doc/ru/smartadtargets/smartadtargets",
        "methods": ["get", "add", "update", "delete", "suspend", "resume", "setBids"],
    },
    "strategies": {
        "resource": "json/v5/strategies",
        "docs": "https://yandex.ru/dev/direct/doc/ru/strategies/strategies",
        "methods": ["get", "add", "update", "archive", "unarchive"],
    },
    "businesses": {
        "resource": "json/v5/businesses",
        "docs": "https://yandex.ru/dev/direct/doc/ru/businesses/businesses",
        "methods": ["get"],
    },
}
