#!/usr/bin/env bash
# Manual checklist for commands that must not be run by automated smoke tests.

set -euo pipefail

cat <<'EOF'
direct-cli DANGEROUS commands manual checklist

This script is documentation, not an executable smoke runner.
Do not run these commands automatically against production or sandbox accounts.

Agency/account mutations:
  - direct agencyclients add ...
  - direct agencyclients update ...
  - direct agencyclients delete ...
  - direct agencyclients add-passport-organization ...
  - direct agencyclients add-passport-organization-member ...

Local credential mutations:
  - direct auth login ...
  - direct auth use ...
  - direct auth logout api --profile NAME
  - direct auth logout browser           (removes both CLI browser sessions)

V4 Live finance money mutations (0.3.3 exposes dry-run-only previews):
  - direct v4finance transfer-money --from-campaign-id ... --to-campaign-id ... --amount ... --currency RUB --dry-run
  - direct v4finance pay-campaigns --campaign-ids ... --amount ... --contract-id ... --pay-method Bank --currency RUB --dry-run

Browser-driven Мастер кампаний mutations (no API surface, no --sandbox
equivalent -- these always hit a real Yandex account; verify on one
non-critical campaign, confirming before/after state in the web UI):
  - direct masters suspend <campaign_id>
  - direct masters resume <campaign_id>
  - direct masters update <campaign_id> --weekly-budget ... (Этап A: also
    --promotion-goal, --directs-helps/--no-directs-helps)
  - direct masters adimages add <campaign_id> --image-file ...
    (uploads real files -- NOT idempotent)
  - direct masters adimages delete <campaign_id> --position ... / --content-id ... / --all
    (can remove every image in the campaign -- NOT idempotent)
  - direct masters adimages set <campaign_id> --image-file ...
    (replaces the ENTIRE image set -- NOT idempotent)
  - direct masters archive <campaign_id>
    (irreversible -- there is no `masters unarchive`)
  - direct masters delete <campaign_id>
    (permanently deletes a DRAFT campaign via the campaigns grid's row
    menu, see issue #782 -- irreversible, and unlike every other masters
    mutation Yandex itself shows NO confirmation dialog before deleting,
    so the CLI prompts for its own confirmation, or pass --yes)
  - direct masters launch <campaign_id>
    (publishes a DRAFT campaign -- irreversible, there is no `masters unlaunch`)
  - direct masters add <url> --headline ... --text ... --region ...
      --add-target-action "<goal_id>=<price>" --weekly-budget ...
    (creates a brand-new campaign -- NOT idempotent, a second run creates a
    second campaign; verify with --draft first, then delete/archive the
    test campaign by hand after checking it in the web UI.
    --add-target-action is REQUIRED (issue #777) -- Yandex's create form
    silently refuses a campaign with no conversion goal. --weekly-budget is
    also REQUIRED (issue #796) for the same reason -- the create form
    silently refuses to submit without a weekly budget too. Note a --draft
    created this way cannot be archived (issue #660) but can be removed
    via `masters delete`, see issue #782)
  - direct masters copy <campaign_id> [--launch/--draft]
    (clones an existing campaign via the overview page's "..." menu, issue
    #659 -- NOT idempotent, a second run creates a second copy, not an
    update. Verify with --draft first, then delete/archive the test copy
    by hand after checking it in the web UI.)

Browser-driven support chat (no API surface, no --sandbox equivalent -- the
text really reaches the Yandex Direct support team):
  - direct support send --message "..."
    (issue #897: sends a real message and may open a support request -- it
    cannot be recalled and is NOT idempotent, a second run is a second
    message. The CLI asks for confirmation, or pass --yes. Use --dry-run to
    preview; verify the result in the chat itself.)
  - direct support rate <1-5>
    (issue #897: presses a rating button in the support bot's "rate our work"
    request -- the rating reaches the support team and cannot be changed. It
    only works while that request is the newest message in the chat. The CLI
    asks for confirmation, or pass --yes. Use --dry-run to preview; verify the
    result in the chat itself.)

Interactive human-in-the-loop login (opens a visible browser window and
blocks waiting for a person to sign in -- cannot run unattended):
  - direct auth login browser

Production commands that are only allowed in automated smoke tests with --sandbox:
  - direct bids set ...
  - direct bids set-auto ...
  - direct keywordbids set ...
  - direct keywordbids set-auto ...
  - direct bidmodifiers set ...
  - direct ads moderate ...
  - direct clients update ...
  - direct campaigns delete ...
  - direct adgroups delete ...
  - direct ads delete ...
  - direct keywords delete ...
  - direct audiencetargets delete ...
  - direct dynamicads delete ...
  - direct dynamicfeedadtargets delete ...
  - direct feeds delete ...
  - direct negativekeywordsharedsets delete ...
  - direct retargeting delete ...
  - direct smartadtargets delete ...
  - direct campaigns suspend/resume/archive/unarchive ...
  - direct ads suspend/resume/archive/unarchive ...
  - direct keywords suspend/resume ...

Use scripts/test_safe_commands.sh for production read-only smoke tests.
Use scripts/test_sandbox_write.sh for sandbox/VCR write smoke tests.
EOF

exit 1
