#!/usr/bin/env python3
"""Live WRITE_SANDBOX runner for the Yandex Direct sandbox API."""

from __future__ import annotations

import argparse
import binascii
import json
import os
import shlex
import struct
import subprocess
import sys
import tempfile
import time
import zlib
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

from direct_cli.smoke_matrix import WRITE_SANDBOX, commands_for_category

PASS = "PASS"
FAIL = "FAIL"
SANDBOX_LIMITATION = "SANDBOX_LIMITATION"
NOT_COVERED = "NOT_COVERED"

SANDBOX_LIMITATION_CODES = {1000, 3500, 5004, 5005, 8300, 8303, 8800}
SANDBOX_LIMITATION_TEXT = (
    "Object not found",
    "Ad group not found",
    "not available in the sandbox",
    "not supported in sandbox",
    "unsupported in sandbox",
    "not allowed for draft",
    "currently unavailable",
)


@dataclass
class CommandRun:
    """Raw subprocess result plus normalized command text."""

    args: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def text(self) -> str:
        return "\n".join(part for part in [self.stdout, self.stderr] if part)

    @property
    def command_text(self) -> str:
        return " ".join(shlex.quote(part) for part in self.args)


@dataclass
class ReportRow:
    """One command row in the live sandbox report."""

    command: str
    status: str
    detail: str
    cli: str = ""


class PrerequisiteError(Exception):
    """Raised when a helper resource could not be prepared."""

    def __init__(self, status: str, detail: str):
        super().__init__(status, detail)
        self.status = status
        self.detail = detail


class LiveSandboxRunner:
    """Execute WRITE_SANDBOX entries through `direct --sandbox`."""

    def __init__(
        self,
        commands: list[str],
        timeout: int,
        verbose: bool,
        report_file: Path | None,
    ) -> None:
        self.commands = commands
        self.timeout = timeout
        self.verbose = verbose
        self.report_file = report_file
        self.suffix = f"live-{int(time.time())}"
        self.root_dir = Path(__file__).resolve().parent.parent
        self.temp_dir = tempfile.TemporaryDirectory(prefix="direct-cli-sandbox-")
        self.temp_path = Path(self.temp_dir.name)
        self.cleanup_steps: list[tuple[str, list[str]]] = []

    def close(self) -> None:
        """Release temporary files."""
        self.temp_dir.cleanup()

    def run(self) -> int:
        """Run the requested matrix entries and print a Markdown report."""
        rows: list[ReportRow] = []
        for command in self.commands:
            row = self.run_one(command)
            rows.append(row)
            print(self.format_row(row), flush=True)

        self.print_summary(rows)
        if self.report_file:
            self.report_file.write_text(self.markdown_report(rows))

        return 1 if any(row.status == FAIL for row in rows) else 0

    def run_one(self, command: str) -> ReportRow:
        """Run one matrix command with best-effort cleanup."""
        self.cleanup_steps = []
        try:
            handler = self.handlers().get(command)
            if handler is None:
                return ReportRow(
                    command=command,
                    status=NOT_COVERED,
                    detail="no safe live scenario is implemented yet",
                )
            return handler(command)
        except PrerequisiteError as exc:
            return ReportRow(command=command, status=exc.status, detail=exc.detail)
        finally:
            self.cleanup_best_effort()

    def handlers(self) -> dict[str, Callable[[str], ReportRow]]:
        """Return command handlers keyed by smoke-matrix command."""
        return {
            "adextensions.add": self.run_adextension_add,
            "adextensions.delete": self.run_adextension_id_command,
            "adgroups.add": self.run_adgroup_add,
            "adgroups.delete": self.run_adgroup_id_command,
            "adgroups.update": self.run_adgroup_id_command,
            "adimages.add": self.run_adimage_add,
            "adimages.delete": self.run_adimage_id_command,
            "ads.add": self.run_ad_add,
            "ads.archive": self.run_ad_id_command,
            "ads.delete": self.run_ad_id_command,
            "ads.moderate": self.run_ad_id_command,
            "ads.resume": self.run_ad_id_command,
            "ads.suspend": self.run_ad_id_command,
            "ads.unarchive": self.run_ad_id_command,
            "ads.update": self.run_ad_id_command,
            "advideos.add": self.run_advideo_add,
            "audiencetargets.add": self.run_audience_target_add,
            "audiencetargets.delete": self.run_audience_target_id_command,
            "audiencetargets.resume": self.run_audience_target_id_command,
            "audiencetargets.set-bids": self.run_audience_target_id_command,
            "audiencetargets.suspend": self.run_audience_target_id_command,
            "bidmodifiers.add": self.run_bidmodifier_add,
            "bidmodifiers.delete": self.run_bidmodifier_id_command,
            "bidmodifiers.set": self.run_bidmodifier_id_command,
            "bids.set": self.run_bid_command,
            "bids.set-auto": self.run_bid_command,
            "campaigns.add": self.run_campaign_add,
            "campaigns.archive": self.run_campaign_id_command,
            "campaigns.delete": self.run_campaign_id_command,
            "campaigns.resume": self.run_campaign_id_command,
            "campaigns.suspend": self.run_campaign_id_command,
            "campaigns.unarchive": self.run_campaign_id_command,
            "campaigns.update": self.run_campaign_id_command,
            "clients.update": self.run_not_covered,
            "creatives.add": self.run_creative_add,
            "dynamicads.add": self.run_dynamic_ad_add,
            "dynamicads.delete": self.run_dynamic_ad_id_command,
            "dynamicads.resume": self.run_dynamic_ad_id_command,
            "dynamicads.set-bids": self.run_dynamic_ad_id_command,
            "dynamicads.suspend": self.run_dynamic_ad_id_command,
            "dynamicfeedadtargets.add": self.run_dynamic_feed_target_add,
            "dynamicfeedadtargets.delete": self.run_dynamic_feed_target_id_command,
            "dynamicfeedadtargets.resume": self.run_dynamic_feed_target_id_command,
            "dynamicfeedadtargets.set-bids": self.run_dynamic_feed_target_id_command,
            "dynamicfeedadtargets.suspend": self.run_dynamic_feed_target_id_command,
            "feeds.add": self.run_feed_add,
            "feeds.delete": self.run_feed_id_command,
            "feeds.update": self.run_feed_id_command,
            "keywordbids.set": self.run_keywordbid_command,
            "keywordbids.set-auto": self.run_keywordbid_command,
            "keywords.add": self.run_keyword_add,
            "keywords.delete": self.run_keyword_id_command,
            "keywords.resume": self.run_keyword_id_command,
            "keywords.suspend": self.run_keyword_id_command,
            "keywords.update": self.run_keyword_id_command,
            "negativekeywordsharedsets.add": self.run_negative_set_add,
            "negativekeywordsharedsets.delete": self.run_negative_set_id_command,
            "negativekeywordsharedsets.update": self.run_negative_set_id_command,
            "retargeting.add": self.run_retargeting_add,
            "retargeting.delete": self.run_retargeting_id_command,
            "retargeting.update": self.run_retargeting_id_command,
            "sitelinks.add": self.run_sitelinks_add,
            "sitelinks.delete": self.run_sitelinks_id_command,
            "smartadtargets.add": self.run_smart_target_add,
            "smartadtargets.delete": self.run_smart_target_id_command,
            "smartadtargets.resume": self.run_smart_target_id_command,
            "smartadtargets.set-bids": self.run_smart_target_id_command,
            "smartadtargets.suspend": self.run_smart_target_id_command,
            "smartadtargets.update": self.run_smart_target_id_command,
            "strategies.add": self.run_strategy_add,
            "strategies.archive": self.run_strategy_id_command,
            "strategies.unarchive": self.run_strategy_id_command,
            "strategies.update": self.run_strategy_id_command,
            "vcards.add": self.run_vcard_add,
            "vcards.delete": self.run_vcard_id_command,
        }

    def invoke(self, group: str, command: str, args: list[str]) -> CommandRun:
        """Run one canonical CLI command against the sandbox API."""
        full_args = ["direct", "--sandbox", group, command, *args]
        if self.verbose:
            print(f"$ {' '.join(shlex.quote(part) for part in full_args)}", flush=True)
        try:
            completed = subprocess.run(
                full_args,
                cwd=self.root_dir,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return CommandRun(
                args=full_args,
                returncode=124,
                stdout=self.decode_timeout_output(exc.stdout),
                stderr=f"timed out after {self.timeout} seconds",
            )
        except OSError as exc:
            return CommandRun(
                args=full_args,
                returncode=127,
                stdout="",
                stderr=str(exc),
            )
        return CommandRun(
            args=full_args,
            returncode=completed.returncode,
            stdout=completed.stdout.strip(),
            stderr=completed.stderr.strip(),
        )

    def decode_timeout_output(self, output: str | bytes | None) -> str:
        """Normalize partial timeout output from subprocess."""
        if output is None:
            return ""
        if isinstance(output, bytes):
            return output.decode(errors="replace").strip()
        return output.strip()

    def row_from_run(self, matrix_command: str, run: CommandRun) -> ReportRow:
        """Classify one CLI invocation."""
        status, detail = self.classify(run, matrix_command)
        return ReportRow(
            command=matrix_command,
            status=status,
            detail=detail,
            cli=run.command_text,
        )

    def classify(
        self, run: CommandRun, matrix_command: str | None = None
    ) -> tuple[str, str]:
        """Convert process and API response details into report status."""
        text = run.text
        if matrix_command == "adimages.delete" and "error_code=1002" in text:
            return SANDBOX_LIMITATION, self.compact(text)
        if run.returncode != 0:
            if self.is_sandbox_limitation(text):
                return SANDBOX_LIMITATION, self.compact(text)
            return FAIL, self.compact(text or f"exit code {run.returncode}")

        parsed = self.parse_json(run.stdout)
        errors = self.find_api_errors(parsed)
        if errors:
            error_text = json.dumps(errors, ensure_ascii=False)
            if self.is_sandbox_limitation(error_text):
                return SANDBOX_LIMITATION, self.compact(error_text)
            return FAIL, self.compact(error_text)

        return PASS, "live sandbox command completed"

    def is_sandbox_limitation(self, text: str) -> bool:
        """Return whether text contains a known sandbox limitation signal."""
        lowered = text.lower()
        if any(marker.lower() in lowered for marker in SANDBOX_LIMITATION_TEXT):
            return True
        for code in SANDBOX_LIMITATION_CODES:
            if f'"Code": {code}' in text or f"'Code': {code}" in text:
                return True
            if f"code {code}" in lowered or f"code={code}" in lowered:
                return True
        return False

    def find_api_errors(self, value: object) -> list[object]:
        """Collect nested Errors blocks from Direct API responses."""
        errors: list[object] = []
        if isinstance(value, dict):
            current = value.get("Errors")
            if current:
                errors.append(current)
            for nested in value.values():
                errors.extend(self.find_api_errors(nested))
        elif isinstance(value, list):
            for item in value:
                errors.extend(self.find_api_errors(item))
        return errors

    def parse_json(self, text: str) -> object | None:
        """Parse JSON output when possible."""
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    def compact(self, text: str, limit: int = 220) -> str:
        """Single-line detail for the report."""
        normalized = " ".join(text.split())
        if len(normalized) > limit:
            return normalized[: limit - 3] + "..."
        return normalized

    def first_id(
        self, run: CommandRun, preferred_keys: tuple[str, ...] = ("Id", "Ids")
    ) -> str | None:
        """Extract the first resource identifier from a successful response."""
        data = self.parse_json(run.stdout)
        return self.first_value(data, preferred_keys)

    def first_value(self, value: object, preferred_keys: tuple[str, ...]) -> str | None:
        """Find the first scalar value for any preferred key in a JSON tree."""
        if isinstance(value, dict):
            for key in preferred_keys:
                if key not in value:
                    continue
                candidate = value[key]
                if isinstance(candidate, list) and candidate:
                    return str(candidate[0])
                if candidate not in (None, "", []):
                    return str(candidate)
            for nested in value.values():
                found = self.first_value(nested, preferred_keys)
                if found:
                    return found
        elif isinstance(value, list):
            for item in value:
                found = self.first_value(item, preferred_keys)
                if found:
                    return found
        return None

    def require_id(
        self,
        label: str,
        run: CommandRun,
        preferred_keys: tuple[str, ...] = ("Id", "Ids"),
    ) -> str:
        """Return a created resource ID or raise a classified prerequisite error."""
        status, detail = self.classify(run)
        if status != PASS:
            raise PrerequisiteError(status, f"{label} prerequisite: {detail}")
        resource_id = self.first_id(run, preferred_keys)
        if not resource_id:
            raise PrerequisiteError(FAIL, f"{label} prerequisite returned no ID")
        return resource_id

    def register_cleanup(
        self, label: str, group: str, command: str, args: list[str]
    ) -> None:
        """Queue best-effort cleanup for a created resource."""
        self.cleanup_steps.append((label, [group, command, *args]))

    def cleanup_best_effort(self) -> None:
        """Run cleanup commands in reverse creation order."""
        for label, command in reversed(self.cleanup_steps):
            group, subcommand, *args = command
            try:
                run = self.invoke(group, subcommand, args)
                if self.verbose and run.returncode != 0:
                    print(f"cleanup {label}: {self.compact(run.text)}", flush=True)
            except (OSError, subprocess.SubprocessError) as exc:
                if self.verbose:
                    print(f"cleanup {label}: {exc}", flush=True)

    def tomorrow(self) -> str:
        """Return a sandbox-safe start date."""
        return (date.today() + timedelta(days=1)).isoformat()

    def name(self, prefix: str) -> str:
        """Build a unique resource name."""
        return f"direct-cli-{prefix}-{self.suffix}"

    def run_not_covered(self, matrix_command: str) -> ReportRow:
        return ReportRow(
            command=matrix_command,
            status=NOT_COVERED,
            detail="requires account-specific existing client data",
        )

    def create_campaign(self, campaign_type: str = "TEXT_CAMPAIGN") -> str:
        args = [
            "--name",
            self.name(campaign_type.lower()),
            "--start-date",
            self.tomorrow(),
            "--type",
            campaign_type,
        ]
        if campaign_type == "SMART_CAMPAIGN":
            args.extend(["--filter-average-cpc", "1"])
        run = self.invoke("campaigns", "add", args)
        campaign_id = self.require_id("campaigns add", run)
        self.register_cleanup("campaign", "campaigns", "delete", ["--id", campaign_id])
        return campaign_id

    def create_adgroup(self, group_type: str = "TEXT_AD_GROUP") -> str:
        campaign_type = "TEXT_CAMPAIGN"
        extra_args: list[str] = []
        if group_type == "DYNAMIC_TEXT_AD_GROUP":
            campaign_type = "DYNAMIC_TEXT_CAMPAIGN"
            extra_args = ["--domain-url", "https://example.com"]
        elif group_type == "SMART_AD_GROUP":
            campaign_type = "SMART_CAMPAIGN"
            feed_id = self.create_feed()
            extra_args = [
                "--feed-id",
                feed_id,
                "--ad-title-source",
                "TITLE",
                "--ad-body-source",
                "DESCRIPTION",
            ]

        campaign_id = self.create_campaign(campaign_type)
        run = self.invoke(
            "adgroups",
            "add",
            [
                "--name",
                self.name(group_type.lower()),
                "--campaign-id",
                campaign_id,
                "--type",
                group_type,
                "--region-ids",
                "225",
                *extra_args,
            ],
        )
        adgroup_id = self.require_id("adgroups add", run)
        self.register_cleanup("adgroup", "adgroups", "delete", ["--id", adgroup_id])
        return adgroup_id

    def create_ad(self) -> str:
        adgroup_id = self.create_adgroup()
        run = self.invoke(
            "ads",
            "add",
            [
                "--adgroup-id",
                adgroup_id,
                "--title",
                "Sandbox test ad",
                "--text",
                "Sandbox test text",
                "--href",
                "https://example.com",
            ],
        )
        ad_id = self.require_id("ads add", run)
        self.register_cleanup("ad", "ads", "delete", ["--id", ad_id])
        return ad_id

    def create_keyword(self) -> str:
        adgroup_id = self.create_adgroup()
        run = self.invoke(
            "keywords",
            "add",
            ["--adgroup-id", adgroup_id, "--keyword", "buy sandbox test"],
        )
        keyword_id = self.require_id("keywords add", run)
        self.register_cleanup("keyword", "keywords", "delete", ["--id", keyword_id])
        return keyword_id

    def create_feed(self) -> str:
        run = self.invoke(
            "feeds",
            "add",
            [
                "--name",
                self.name("feed"),
                "--url",
                "https://example.com/feed.xml",
            ],
        )
        feed_id = self.require_id("feeds add", run)
        self.register_cleanup("feed", "feeds", "delete", ["--id", feed_id])
        return feed_id

    def create_retargeting(self) -> str:
        run = self.invoke(
            "retargeting",
            "add",
            [
                "--name",
                self.name("retargeting"),
                "--type",
                "RETARGETING",
                "--rule",
                "ANY:1234567890",
            ],
        )
        list_id = self.require_id("retargeting add", run)
        self.register_cleanup("retargeting", "retargeting", "delete", ["--id", list_id])
        return list_id

    def create_adextension(self) -> str:
        run = self.invoke("adextensions", "add", ["--callout-text", "Free shipping"])
        extension_id = self.require_id("adextensions add", run)
        self.register_cleanup(
            "adextension", "adextensions", "delete", ["--id", extension_id]
        )
        return extension_id

    def create_sitelinks(self) -> str:
        run = self.invoke(
            "sitelinks",
            "add",
            [
                "--sitelink",
                "About|https://example.com/about",
                "--sitelink",
                "Contact|https://example.com/contact",
            ],
        )
        set_id = self.require_id("sitelinks add", run)
        self.register_cleanup("sitelinks", "sitelinks", "delete", ["--id", set_id])
        return set_id

    def create_negative_set(self) -> str:
        run = self.invoke(
            "negativekeywordsharedsets",
            "add",
            [
                "--name",
                self.name("negative"),
                "--keywords",
                "spam,blocked",
            ],
        )
        set_id = self.require_id("negativekeywordsharedsets add", run)
        self.register_cleanup(
            "negative set",
            "negativekeywordsharedsets",
            "delete",
            ["--id", set_id],
        )
        return set_id

    def create_bidmodifier(self) -> str:
        campaign_id = self.create_campaign()
        run = self.invoke(
            "bidmodifiers",
            "add",
            [
                "--campaign-id",
                campaign_id,
                "--type",
                "MOBILE_ADJUSTMENT",
                "--value",
                "120",
            ],
        )
        modifier_id = self.require_id("bidmodifiers add", run)
        self.register_cleanup(
            "bidmodifier", "bidmodifiers", "delete", ["--id", modifier_id]
        )
        return modifier_id

    def create_audience_target(self) -> str:
        adgroup_id = self.create_adgroup()
        retargeting_id = self.create_retargeting()
        run = self.invoke(
            "audiencetargets",
            "add",
            [
                "--adgroup-id",
                adgroup_id,
                "--retargeting-list-id",
                retargeting_id,
            ],
        )
        target_id = self.require_id("audiencetargets add", run)
        self.register_cleanup(
            "audience target", "audiencetargets", "delete", ["--id", target_id]
        )
        return target_id

    def create_dynamic_ad_target(self) -> str:
        adgroup_id = self.create_adgroup("DYNAMIC_TEXT_AD_GROUP")
        run = self.invoke(
            "dynamicads",
            "add",
            [
                "--adgroup-id",
                adgroup_id,
                "--name",
                self.name("dynamic-target"),
                "--condition",
                "URL:CONTAINS_ANY:test",
            ],
        )
        target_id = self.require_id("dynamicads add", run)
        self.register_cleanup(
            "dynamic ad target", "dynamicads", "delete", ["--id", target_id]
        )
        return target_id

    def create_smart_target(self) -> str:
        adgroup_id = self.create_adgroup("SMART_AD_GROUP")
        run = self.invoke(
            "smartadtargets",
            "add",
            [
                "--adgroup-id",
                adgroup_id,
                "--name",
                self.name("smart-target"),
                "--audience",
                "ALL_SEGMENTS",
            ],
        )
        target_id = self.require_id("smartadtargets add", run)
        self.register_cleanup(
            "smart target", "smartadtargets", "delete", ["--id", target_id]
        )
        return target_id

    def create_dynamic_feed_target(self) -> str:
        adgroup_id = self.create_adgroup("SMART_AD_GROUP")
        run = self.invoke(
            "dynamicfeedadtargets",
            "add",
            [
                "--adgroup-id",
                adgroup_id,
                "--name",
                self.name("dynamic-feed-target"),
                "--available-items-only",
                "NO",
            ],
        )
        target_id = self.require_id("dynamicfeedadtargets add", run)
        self.register_cleanup(
            "dynamic feed target",
            "dynamicfeedadtargets",
            "delete",
            ["--id", target_id],
        )
        return target_id

    def create_strategy(self) -> str:
        run = self.invoke(
            "strategies",
            "add",
            [
                "--name",
                self.name("strategy"),
                "--type",
                "AverageCpc",
                "--params",
                '{"AverageCpc":1000000}',
            ],
        )
        strategy_id = self.require_id("strategies add", run)
        self.register_cleanup(
            "strategy", "strategies", "archive", ["--id", strategy_id]
        )
        return strategy_id

    def create_vcard(self) -> str:
        campaign_id = self.create_campaign()
        run = self.invoke(
            "vcards",
            "add",
            [
                "--campaign-id",
                campaign_id,
                "--country",
                "Россия",
                "--city",
                "Москва",
                "--company-name",
                "Test Company",
                "--work-time",
                "1#5#9#0#18#0",
                "--phone-country-code",
                "+7",
                "--phone-city-code",
                "495",
                "--phone-number",
                "1234567",
            ],
        )
        vcard_id = self.require_id("vcards add", run)
        self.register_cleanup("vcard", "vcards", "delete", ["--id", vcard_id])
        return vcard_id

    def create_adimage(self) -> str:
        image_path = self.temp_path / "sandbox-image.png"
        image_path.write_bytes(self.make_png(450, 450, (220, 20, 20)))
        run = self.invoke(
            "adimages",
            "add",
            ["--name", "sandbox-image.png", "--image-file", str(image_path)],
        )
        image_hash = self.require_id("adimages add", run, ("AdImageHash", "Hash", "Id"))
        self.register_cleanup("adimage", "adimages", "delete", ["--hash", image_hash])
        return image_hash

    def create_advideo(self) -> str:
        video_path = self.root_dir / "tests" / "fixtures" / "test-video.mp4"
        run = self.invoke(
            "advideos",
            "add",
            ["--video-file", str(video_path), "--name", self.name("video")],
        )
        return self.require_id("advideos add", run, ("Id", "Ids"))

    def make_png(self, width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
        """Create a simple RGB PNG without external dependencies."""
        raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

        def chunk(kind: bytes, payload: bytes) -> bytes:
            return (
                struct.pack(">I", len(payload))
                + kind
                + payload
                + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)
            )

        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b"")
        )

    def run_campaign_add(self, matrix_command: str) -> ReportRow:
        run = self.invoke(
            "campaigns",
            "add",
            ["--name", self.name("campaign"), "--start-date", self.tomorrow()],
        )
        campaign_id = self.first_id(run)
        if campaign_id:
            self.register_cleanup(
                "campaign", "campaigns", "delete", ["--id", campaign_id]
            )
        return self.row_from_run(matrix_command, run)

    def run_campaign_id_command(self, matrix_command: str) -> ReportRow:
        campaign_id = self.create_campaign()
        command = matrix_command.split(".", 1)[1]
        args = ["--id", campaign_id]
        if command == "update":
            args.extend(["--name", self.name("campaign-renamed")])
        run = self.invoke("campaigns", command, args)
        if command == "delete" and self.classify(run)[0] == PASS:
            self.cleanup_steps = [
                step for step in self.cleanup_steps if step[0] != "campaign"
            ]
        return self.row_from_run(matrix_command, run)

    def run_adgroup_add(self, matrix_command: str) -> ReportRow:
        campaign_id = self.create_campaign()
        run = self.invoke(
            "adgroups",
            "add",
            [
                "--name",
                self.name("adgroup"),
                "--campaign-id",
                campaign_id,
                "--region-ids",
                "225",
            ],
        )
        adgroup_id = self.first_id(run)
        if adgroup_id:
            self.register_cleanup("adgroup", "adgroups", "delete", ["--id", adgroup_id])
        return self.row_from_run(matrix_command, run)

    def run_adgroup_id_command(self, matrix_command: str) -> ReportRow:
        adgroup_id = self.create_adgroup()
        command = matrix_command.split(".", 1)[1]
        args = ["--id", adgroup_id]
        if command == "update":
            args.extend(["--name", self.name("adgroup-renamed")])
        return self.row_from_run(matrix_command, self.invoke("adgroups", command, args))

    def run_ad_add(self, matrix_command: str) -> ReportRow:
        adgroup_id = self.create_adgroup()
        run = self.invoke(
            "ads",
            "add",
            [
                "--adgroup-id",
                adgroup_id,
                "--title",
                "Sandbox test ad",
                "--text",
                "Sandbox test text",
                "--href",
                "https://example.com",
            ],
        )
        ad_id = self.first_id(run)
        if ad_id:
            self.register_cleanup("ad", "ads", "delete", ["--id", ad_id])
        return self.row_from_run(matrix_command, run)

    def run_ad_id_command(self, matrix_command: str) -> ReportRow:
        ad_id = self.create_ad()
        command = matrix_command.split(".", 1)[1]
        args = ["--id", ad_id]
        if command == "update":
            args.extend(["--title", "Updated sandbox title"])
        return self.row_from_run(matrix_command, self.invoke("ads", command, args))

    def run_keyword_add(self, matrix_command: str) -> ReportRow:
        adgroup_id = self.create_adgroup()
        run = self.invoke(
            "keywords",
            "add",
            ["--adgroup-id", adgroup_id, "--keyword", "buy sandbox test"],
        )
        keyword_id = self.first_id(run)
        if keyword_id:
            self.register_cleanup("keyword", "keywords", "delete", ["--id", keyword_id])
        return self.row_from_run(matrix_command, run)

    def run_keyword_id_command(self, matrix_command: str) -> ReportRow:
        keyword_id = self.create_keyword()
        command = matrix_command.split(".", 1)[1]
        args = ["--id", keyword_id]
        if command == "update":
            args.extend(["--keyword", "buy sandbox test updated"])
        return self.row_from_run(matrix_command, self.invoke("keywords", command, args))

    def run_bid_command(self, matrix_command: str) -> ReportRow:
        keyword_id = self.create_keyword()
        command = matrix_command.split(".", 1)[1]
        args = ["--keyword-id", keyword_id]
        if command == "set":
            args.extend(["--bid", "10"])
        else:
            args.extend(
                ["--scope", "SEARCH", "--position", "PREMIUMBLOCK", "--max-bid", "10"]
            )
        return self.row_from_run(matrix_command, self.invoke("bids", command, args))

    def run_keywordbid_command(self, matrix_command: str) -> ReportRow:
        keyword_id = self.create_keyword()
        command = matrix_command.split(".", 1)[1]
        args = ["--keyword-id", keyword_id]
        if command == "set":
            args.extend(["--search-bid", "8", "--network-bid", "3"])
        else:
            args.extend(["--target-traffic-volume", "75", "--bid-ceiling", "10"])
        return self.row_from_run(
            matrix_command, self.invoke("keywordbids", command, args)
        )

    def run_bidmodifier_add(self, matrix_command: str) -> ReportRow:
        campaign_id = self.create_campaign()
        run = self.invoke(
            "bidmodifiers",
            "add",
            [
                "--campaign-id",
                campaign_id,
                "--type",
                "MOBILE_ADJUSTMENT",
                "--value",
                "120",
            ],
        )
        modifier_id = self.first_id(run)
        if modifier_id:
            self.register_cleanup(
                "bidmodifier", "bidmodifiers", "delete", ["--id", modifier_id]
            )
        return self.row_from_run(matrix_command, run)

    def run_bidmodifier_id_command(self, matrix_command: str) -> ReportRow:
        modifier_id = self.create_bidmodifier()
        command = matrix_command.split(".", 1)[1]
        args = ["--id", modifier_id]
        if command == "set":
            args.extend(["--value", "110"])
        return self.row_from_run(
            matrix_command, self.invoke("bidmodifiers", command, args)
        )

    def run_feed_add(self, matrix_command: str) -> ReportRow:
        run = self.invoke(
            "feeds",
            "add",
            ["--name", self.name("feed"), "--url", "https://example.com/feed.xml"],
        )
        feed_id = self.first_id(run)
        if feed_id:
            self.register_cleanup("feed", "feeds", "delete", ["--id", feed_id])
        return self.row_from_run(matrix_command, run)

    def run_feed_id_command(self, matrix_command: str) -> ReportRow:
        feed_id = self.create_feed()
        command = matrix_command.split(".", 1)[1]
        args = ["--id", feed_id]
        if command == "update":
            args.extend(["--name", self.name("feed-renamed")])
        return self.row_from_run(matrix_command, self.invoke("feeds", command, args))

    def run_retargeting_add(self, matrix_command: str) -> ReportRow:
        run = self.invoke(
            "retargeting",
            "add",
            ["--name", self.name("retargeting"), "--rule", "ANY:1234567890"],
        )
        list_id = self.first_id(run)
        if list_id:
            self.register_cleanup(
                "retargeting", "retargeting", "delete", ["--id", list_id]
            )
        return self.row_from_run(matrix_command, run)

    def run_retargeting_id_command(self, matrix_command: str) -> ReportRow:
        list_id = self.create_retargeting()
        command = matrix_command.split(".", 1)[1]
        args = ["--id", list_id]
        if command == "update":
            args.extend(["--name", self.name("retargeting-renamed")])
        return self.row_from_run(
            matrix_command, self.invoke("retargeting", command, args)
        )

    def run_adextension_add(self, matrix_command: str) -> ReportRow:
        run = self.invoke("adextensions", "add", ["--callout-text", "Free shipping"])
        extension_id = self.first_id(run)
        if extension_id:
            self.register_cleanup(
                "adextension", "adextensions", "delete", ["--id", extension_id]
            )
        return self.row_from_run(matrix_command, run)

    def run_adextension_id_command(self, matrix_command: str) -> ReportRow:
        extension_id = self.create_adextension()
        return self.row_from_run(
            matrix_command,
            self.invoke("adextensions", "delete", ["--id", extension_id]),
        )

    def run_sitelinks_add(self, matrix_command: str) -> ReportRow:
        run = self.invoke(
            "sitelinks",
            "add",
            [
                "--sitelink",
                "About|https://example.com/about",
                "--sitelink",
                "Contact|https://example.com/contact",
            ],
        )
        set_id = self.first_id(run)
        if set_id:
            self.register_cleanup("sitelinks", "sitelinks", "delete", ["--id", set_id])
        return self.row_from_run(matrix_command, run)

    def run_sitelinks_id_command(self, matrix_command: str) -> ReportRow:
        set_id = self.create_sitelinks()
        return self.row_from_run(
            matrix_command,
            self.invoke("sitelinks", "delete", ["--id", set_id]),
        )

    def run_negative_set_add(self, matrix_command: str) -> ReportRow:
        run = self.invoke(
            "negativekeywordsharedsets",
            "add",
            ["--name", self.name("negative"), "--keywords", "spam,blocked"],
        )
        set_id = self.first_id(run)
        if set_id:
            self.register_cleanup(
                "negative set", "negativekeywordsharedsets", "delete", ["--id", set_id]
            )
        return self.row_from_run(matrix_command, run)

    def run_negative_set_id_command(self, matrix_command: str) -> ReportRow:
        set_id = self.create_negative_set()
        command = matrix_command.split(".", 1)[1]
        args = ["--id", set_id]
        if command == "update":
            args.extend(["--keywords", "spam,blocked,trash"])
        return self.row_from_run(
            matrix_command, self.invoke("negativekeywordsharedsets", command, args)
        )

    def run_vcard_add(self, matrix_command: str) -> ReportRow:
        campaign_id = self.create_campaign()
        run = self.invoke(
            "vcards",
            "add",
            [
                "--campaign-id",
                campaign_id,
                "--country",
                "Россия",
                "--city",
                "Москва",
                "--company-name",
                "Test Company",
                "--work-time",
                "1#5#9#0#18#0",
                "--phone-country-code",
                "+7",
                "--phone-city-code",
                "495",
                "--phone-number",
                "1234567",
            ],
        )
        vcard_id = self.first_id(run)
        if vcard_id:
            self.register_cleanup("vcard", "vcards", "delete", ["--id", vcard_id])
        return self.row_from_run(matrix_command, run)

    def run_vcard_id_command(self, matrix_command: str) -> ReportRow:
        vcard_id = self.create_vcard()
        return self.row_from_run(
            matrix_command, self.invoke("vcards", "delete", ["--id", vcard_id])
        )

    def run_adimage_add(self, matrix_command: str) -> ReportRow:
        image_path = self.temp_path / "sandbox-image.png"
        image_path.write_bytes(self.make_png(450, 450, (220, 20, 20)))
        run = self.invoke(
            "adimages",
            "add",
            ["--name", "sandbox-image.png", "--image-file", str(image_path)],
        )
        image_hash = self.first_id(run, ("AdImageHash", "Hash", "Id"))
        if image_hash:
            self.register_cleanup(
                "adimage", "adimages", "delete", ["--hash", image_hash]
            )
        return self.row_from_run(matrix_command, run)

    def run_adimage_id_command(self, matrix_command: str) -> ReportRow:
        image_hash = self.create_adimage()
        return self.row_from_run(
            matrix_command,
            self.invoke("adimages", "delete", ["--hash", image_hash]),
        )

    def run_advideo_add(self, matrix_command: str) -> ReportRow:
        video_path = self.root_dir / "tests" / "fixtures" / "test-video.mp4"
        run = self.invoke(
            "advideos",
            "add",
            ["--video-file", str(video_path), "--name", self.name("video")],
        )
        return self.row_from_run(matrix_command, run)

    def run_creative_add(self, matrix_command: str) -> ReportRow:
        video_id = self.create_advideo()
        return self.row_from_run(
            matrix_command,
            self.invoke("creatives", "add", ["--video-id", video_id]),
        )

    def run_audience_target_add(self, matrix_command: str) -> ReportRow:
        adgroup_id = self.create_adgroup()
        retargeting_id = self.create_retargeting()
        run = self.invoke(
            "audiencetargets",
            "add",
            ["--adgroup-id", adgroup_id, "--retargeting-list-id", retargeting_id],
        )
        target_id = self.first_id(run)
        if target_id:
            self.register_cleanup(
                "audience target", "audiencetargets", "delete", ["--id", target_id]
            )
        return self.row_from_run(matrix_command, run)

    def run_audience_target_id_command(self, matrix_command: str) -> ReportRow:
        target_id = self.create_audience_target()
        command = matrix_command.split(".", 1)[1]
        args = ["--id", target_id]
        if command == "set-bids":
            args.extend(["--context-bid", "5"])
        return self.row_from_run(
            matrix_command, self.invoke("audiencetargets", command, args)
        )

    def run_dynamic_ad_add(self, matrix_command: str) -> ReportRow:
        adgroup_id = self.create_adgroup("DYNAMIC_TEXT_AD_GROUP")
        run = self.invoke(
            "dynamicads",
            "add",
            [
                "--adgroup-id",
                adgroup_id,
                "--name",
                self.name("dynamic-target"),
                "--condition",
                "URL:CONTAINS_ANY:test",
            ],
        )
        target_id = self.first_id(run)
        if target_id:
            self.register_cleanup(
                "dynamic ad target", "dynamicads", "delete", ["--id", target_id]
            )
        return self.row_from_run(matrix_command, run)

    def run_dynamic_ad_id_command(self, matrix_command: str) -> ReportRow:
        target_id = self.create_dynamic_ad_target()
        command = matrix_command.split(".", 1)[1]
        args = ["--id", target_id]
        if command == "set-bids":
            args.extend(["--bid", "10"])
        return self.row_from_run(
            matrix_command, self.invoke("dynamicads", command, args)
        )

    def run_smart_target_add(self, matrix_command: str) -> ReportRow:
        adgroup_id = self.create_adgroup("SMART_AD_GROUP")
        run = self.invoke(
            "smartadtargets",
            "add",
            [
                "--adgroup-id",
                adgroup_id,
                "--name",
                self.name("smart-target"),
                "--audience",
                "ALL_SEGMENTS",
            ],
        )
        target_id = self.first_id(run)
        if target_id:
            self.register_cleanup(
                "smart target", "smartadtargets", "delete", ["--id", target_id]
            )
        return self.row_from_run(matrix_command, run)

    def run_smart_target_id_command(self, matrix_command: str) -> ReportRow:
        target_id = self.create_smart_target()
        command = matrix_command.split(".", 1)[1]
        args = ["--id", target_id]
        if command == "update":
            args.extend(["--priority", "HIGH"])
        elif command == "set-bids":
            args.extend(["--average-cpc", "5"])
        return self.row_from_run(
            matrix_command, self.invoke("smartadtargets", command, args)
        )

    def run_dynamic_feed_target_add(self, matrix_command: str) -> ReportRow:
        adgroup_id = self.create_adgroup("SMART_AD_GROUP")
        run = self.invoke(
            "dynamicfeedadtargets",
            "add",
            [
                "--adgroup-id",
                adgroup_id,
                "--name",
                self.name("dynamic-feed-target"),
                "--available-items-only",
                "NO",
            ],
        )
        target_id = self.first_id(run)
        if target_id:
            self.register_cleanup(
                "dynamic feed target",
                "dynamicfeedadtargets",
                "delete",
                ["--id", target_id],
            )
        return self.row_from_run(matrix_command, run)

    def run_dynamic_feed_target_id_command(self, matrix_command: str) -> ReportRow:
        target_id = self.create_dynamic_feed_target()
        command = matrix_command.split(".", 1)[1]
        args = ["--id", target_id]
        if command == "set-bids":
            args.extend(["--bid", "10"])
        return self.row_from_run(
            matrix_command, self.invoke("dynamicfeedadtargets", command, args)
        )

    def run_strategy_add(self, matrix_command: str) -> ReportRow:
        run = self.invoke(
            "strategies",
            "add",
            [
                "--name",
                self.name("strategy"),
                "--type",
                "AverageCpc",
                "--params",
                '{"AverageCpc":1000000}',
            ],
        )
        strategy_id = self.first_id(run)
        if strategy_id:
            self.register_cleanup(
                "strategy", "strategies", "archive", ["--id", strategy_id]
            )
        return self.row_from_run(matrix_command, run)

    def run_strategy_id_command(self, matrix_command: str) -> ReportRow:
        strategy_id = self.create_strategy()
        command = matrix_command.split(".", 1)[1]
        args = ["--id", strategy_id]
        if command == "update":
            args.extend(["--name", self.name("strategy-renamed")])
        return self.row_from_run(
            matrix_command, self.invoke("strategies", command, args)
        )

    def format_row(self, row: ReportRow) -> str:
        return f"{row.status:18} {row.command:36} {row.detail}"

    def markdown_report(self, rows: list[ReportRow]) -> str:
        lines = [
            "# WRITE_SANDBOX live sandbox report",
            "",
            f"WRITE_SANDBOX commands: {len(rows)}",
            "",
            "| Status | Command | Detail |",
            "| --- | --- | --- |",
        ]
        for row in rows:
            detail = row.detail.replace("|", "\\|")
            lines.append(f"| {row.status} | `{row.command}` | {detail} |")
        lines.append("")
        return "\n".join(lines)

    def print_summary(self, rows: list[ReportRow]) -> None:
        counts = {status: 0 for status in [PASS, SANDBOX_LIMITATION, FAIL, NOT_COVERED]}
        for row in rows:
            counts[row.status] += 1
        print()
        print(f"WRITE_SANDBOX commands: {len(rows)}")
        for status in [PASS, SANDBOX_LIMITATION, FAIL, NOT_COVERED]:
            print(f"{status}: {counts[status]}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run WRITE_SANDBOX commands against the live Yandex Direct sandbox."
    )
    parser.add_argument(
        "--command",
        action="append",
        choices=commands_for_category(WRITE_SANDBOX),
        help="Run only this matrix command; may be passed multiple times.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=90,
        help="Per-command timeout in seconds.",
    )
    parser.add_argument("--verbose", action="store_true", help="Print CLI calls.")
    parser.add_argument("--report-file", type=Path, help="Write Markdown report.")
    return parser.parse_args(argv)


def validate_environment() -> None:
    missing = [
        name
        for name in ["YANDEX_DIRECT_TOKEN", "YANDEX_DIRECT_LOGIN"]
        if not os.environ.get(name)
    ]
    if missing:
        raise SystemExit(f"ERROR: missing required environment: {', '.join(missing)}")


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    validate_environment()
    commands = args.command or commands_for_category(WRITE_SANDBOX)
    print("direct-cli WRITE_SANDBOX live sandbox")
    print(f"WRITE_SANDBOX commands: {len(commands)}")
    print("endpoint: api-sandbox.direct.yandex.com")
    print()

    runner = LiveSandboxRunner(
        commands=commands,
        timeout=args.timeout,
        verbose=args.verbose,
        report_file=args.report_file,
    )
    try:
        return runner.run()
    finally:
        runner.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
