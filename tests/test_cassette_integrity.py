"""Offline integrity guards for committed live-write cassettes.

Unlike ``test_v5_live_write.py`` (gated behind ``YANDEX_DIRECT_LIVE_WRITE=1``),
these tests always run — they only read committed cassette files from disk, with
no token and no network. They catch a cassette that was accidentally re-recorded
into a degraded shape (e.g. a full lifecycle overwritten by a skip-only,
add-rejected recording) before it can hide missing coverage in CI.
"""

from __future__ import annotations

import os

CASSETTE_DIR = os.path.join(
    os.path.dirname(__file__), "cassettes", "test_v5_live_write"
)


def _cassette_body(name: str) -> str:
    path = os.path.join(CASSETTE_DIR, name)
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def test_retargeting_cassette_records_full_lifecycle() -> None:
    """The committed retargeting cassette must hold add/update/delete.

    ``_retargeting_goal()`` falls back to the synthetic ``12345`` when
    ``YANDEX_DIRECT_TEST_RETARGETING_GOAL_ID`` is unset, which the live API
    rejects with 8800, so a ``--record-mode=rewrite`` run on a machine without a
    real goal would silently overwrite the full-lifecycle cassette with a
    rejected add-only one — after which replay *skips* instead of proving
    update/delete coverage. This guard fails if any lifecycle method is missing,
    catching that regression offline.
    """
    body = _cassette_body(
        "test_v5_live_draft_retargeting_add_update_delete.yaml"
    )
    for method in ('"method":"add"', '"method":"update"', '"method":"delete"'):
        assert method in body, (
            f"retargeting cassette is missing {method} — it looks re-recorded "
            "as a skip-only (add-rejected) cassette. Re-record with "
            "YANDEX_DIRECT_TEST_RETARGETING_GOAL_ID set to a real goal."
        )


def test_audiencetargets_add_delete_cassette_records_full_lifecycle() -> None:
    """The committed audiencetargets add/delete cassette must hold add+delete.

    Like the retargeting list, audiencetargets bind a Metrica goal whose synthetic
    ``12345`` fallback the live API rejects with 8800, so a re-record on a machine
    without ``YANDEX_DIRECT_TEST_RETARGETING_GOAL_ID`` would silently degrade the
    full lifecycle to a skip-only, add-rejected cassette. This guard fails offline
    if either lifecycle method is missing.
    """
    body = _cassette_body(
        "test_v5_live_draft_audiencetargets_add_delete.yaml"
    )
    for method in ('"method":"add"', '"method":"delete"'):
        assert method in body, (
            f"audiencetargets add/delete cassette is missing {method} — it looks "
            "re-recorded as a skip-only (add-rejected) cassette. Re-record with "
            "YANDEX_DIRECT_TEST_RETARGETING_GOAL_ID set to a real goal."
        )


def test_audiencetargets_suspend_resume_cassette_records_full_lifecycle() -> None:
    """The committed audiencetargets suspend/resume cassette must hold the lifecycle.

    Same silent-degradation exposure as the add/delete cassette: a goalless
    re-record turns the add+delete+suspend+resume lifecycle into a skip-only
    recording. This guard fails offline if any lifecycle method is missing.
    """
    body = _cassette_body(
        "test_v5_live_draft_audiencetargets_suspend_resume.yaml"
    )
    for method in (
        '"method":"add"',
        '"method":"delete"',
        '"method":"suspend"',
        '"method":"resume"',
    ):
        assert method in body, (
            f"audiencetargets suspend/resume cassette is missing {method} — it "
            "looks re-recorded as a skip-only (add-rejected) cassette. Re-record "
            "with YANDEX_DIRECT_TEST_RETARGETING_GOAL_ID set to a real goal."
        )
