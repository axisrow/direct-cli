#!/usr/bin/env python3
"""Read-only recon for issue #761 (NO mutation unless --mutate is passed).

Discovers the exact ``data-testid`` of the "UTM-метки и параметры URL" field
(``CampaignLinkEditorLite.UTMInput``) on the Мастер кампаний EDIT page, its
widget type, and the current LinkInput / UTMInput baseline values for the
test master campaign.

With ``--mutate`` (coordinated live window ONLY): applies the hypothesised
fix — bare path -> LinkInput, query string -> UTMInput — saves, reloads,
re-reads, prints whether Yandex accepted it, then RESTORES the exact original
state (link + utm) and re-reads to confirm. Uses direct Playwright, NOT the
CLI's ``_set_landing_url`` (which is what we're validating), so it can restore
the original even if the CLI would re-split.
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional, Tuple


CAMPAIGN_ID = 713234191
WIZARD_EDIT_URL = f"https://direct.yandex.ru/wizard/campaigns/{CAMPAIGN_ID}/edit/"

# Known from masters.py (issue #757):
LINK_INPUT = '[data-testid="CampaignLinkEditorLite.LinkInput.Textinput"]'
LINK_CLEAR = '[data-testid="CampaignLinkEditorLite.LinkInput.Textinput.Clear"]'
# Discovered by recon (issue #761): the UTM field is a contenteditable
# role=textbox lazily mounted under the "Дополнительные параметры" spoiler.
UTM_INPUT = '[data-testid="CampaignLinkEditorLite.UTMInput"]'


def _open_session(headless: bool):
    from direct_cli.browser.session import open_saved_session

    return open_saved_session(headless=headless)


def _wait_edit_form(page) -> None:
    from direct_cli.browser.masters import _wait_for_edit_form
    from direct_cli.browser.session import assert_authenticated, assert_not_captcha

    page.goto(WIZARD_EDIT_URL, wait_until="commit")
    assert_not_captcha(page.content())
    assert_authenticated(page.content())
    _wait_for_edit_form(page, CAMPAIGN_ID)


_SPOILER_BUTTON = '[data-testid="CampaignLinkEditorLite.Spoiler.Button"]'


def _spoiler_expanded(page) -> Optional[bool]:
    btn = page.locator(_SPOILER_BUTTON).first
    try:
        if btn.count() == 0:
            return None
        return btn.get_attribute("aria-expanded") == "true"
    except Exception:
        return None


def _expand_advanced_params(page) -> bool:
    """Click 'Дополнительные параметры' to reveal the UTMInput field.

    The UTM field lives under a collapsed spoiler; its data-testid only mounts
    after expansion. Tries a Playwright click, then a direct JS click. No save.
    """
    # Dump spoiler outerHTML once for diagnosis.
    try:
        html = page.evaluate(
            "() => { const e = document.querySelector("
            "'[data-testid=\"CampaignLinkEditorLite.Spoiler\"]'"
            "); return e ? e.outerHTML.slice(0, 600) : null; }"
        )
        print(f"  [diag] Spoiler outerHTML: {html!r}")
    except Exception as exc:
        print(f"  [diag] could not read spoiler html: {exc!r}")

    for _ in range(3):
        if _spoiler_expanded(page):
            return True
        btn = page.locator(_SPOILER_BUTTON).first
        try:
            if btn.count() > 0:
                btn.scroll_into_view_if_needed()
                btn.click()
        except Exception:
            pass
        for _ in range(20):
            page.wait_for_timeout(100)
            if _spoiler_expanded(page):
                return True
        # Fallback: direct JS click.
        try:
            page.evaluate(
                "() => { const b = document.querySelector("
                "'[data-testid=\"CampaignLinkEditorLite.Spoiler.Button\"]'"
                "); if (b) b.click(); }"
            )
        except Exception:
            pass
        for _ in range(20):
            page.wait_for_timeout(100)
            if _spoiler_expanded(page):
                return True
    return False


def _dump_link_editor_subtree(page) -> None:
    """Dump the full CampaignLinkEditorLite subtree + spoiler state."""
    js = r"""
    () => {
      const root = document.querySelector('[data-testid="CampaignLinkEditorLite"]');
      if (!root) return {error: 'no CampaignLinkEditorLite root'};
      const spoilerBtn = document.querySelector('[data-testid="CampaignLinkEditorLite.Spoiler.Button"]');
      const out = {
        spoiler_aria_expanded: spoilerBtn ? spoilerBtn.getAttribute('aria-expanded') : null,
        spoiler_text: spoilerBtn ? (spoilerBtn.textContent||'').trim() : null,
        nodes: [],
      };
      const walk = (el, depth) => {
        if (depth > 6) return;
        const testid = el.getAttribute && el.getAttribute('data-testid');
        const role = el.getAttribute && el.getAttribute('role');
        const editable = el.getAttribute && el.getAttribute('contenteditable');
        const placeholder = el.getAttribute && (el.getAttribute('placeholder') || el.getAttribute('data-placeholder'));
        const ariaExpanded = el.getAttribute && el.getAttribute('aria-expanded');
        const hidden = el.getAttribute && el.getAttribute('hidden');
        // Only record elements that carry identifying info.
        if (testid || role === 'textbox' || el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || ariaExpanded) {
          out.nodes.push({
            depth,
            tag: el.tagName.toLowerCase(),
            testid: testid || '',
            role: role || '',
            editable: editable || '',
            placeholder: placeholder || '',
            ariaExpanded: ariaExpanded || '',
            hidden: hidden !== null ? hidden : '',
            text: (el.textContent || '').slice(0, 60),
          });
        }
        for (const c of el.children) walk(c, depth + 1);
      };
      walk(root, 0);
      return out;
    }
    """
    data = page.evaluate(js)
    print("=== CampaignLinkEditorLite subtree ===")
    if isinstance(data, dict) and data.get("error"):
        print(f"  {data['error']}")
        print()
        return
    print(f"  spoiler aria-expanded={data.get('spoiler_aria_expanded')!r} text={data.get('spoiler_text')!r}")
    for n in data.get("nodes", []):
        indent = "  " + ("  " * n["depth"])
        print(
            f"{indent}<{n['tag']}> testid={n['testid']!r} role={n['role']!r} "
            f"editable={n['editable']!r} ph={n['placeholder']!r} "
            f"aria-exp={n['ariaExpanded']!r} hidden={n['hidden']!r} text={n['text']!r}"
        )
    print()


def _dump_url_editor_dom(page) -> None:
    """Print every data-testid containing Link/UTM/Url/CampaignLinkEditor, plus
    every textbox/input/textarea on the page (the UTM field may carry a generic
    testid or none)."""
    js = r"""
    () => {
      const out = [];
      document.querySelectorAll('[data-testid]').forEach(el => {
        const t = el.getAttribute('data-testid') || '';
        if (/Link|UTM|Url|CampaignLinkEditor|Sitelink/i.test(t)) {
          out.push({
            kind: 'testid',
            testid: t,
            tag: el.tagName.toLowerCase(),
            role: el.getAttribute('role') || '',
            contentEditable: el.getAttribute('contenteditable') || '',
            placeholder: el.getAttribute('placeholder') || (el.getAttribute('data-placeholder') || ''),
            text: (el.textContent || '').slice(0, 100),
          });
        }
      });
      document.querySelectorAll('[role="textbox"], input, textarea').forEach(el => {
        out.push({
          kind: 'input',
          testid: el.getAttribute('data-testid') || '',
          tag: el.tagName.toLowerCase(),
          role: el.getAttribute('role') || '',
          contentEditable: el.getAttribute('contenteditable') || '',
          placeholder: el.getAttribute('placeholder') || (el.getAttribute('data-placeholder') || ''),
          value: el.value || '',
          text: (el.textContent || '').slice(0, 100),
        });
      });
      return out;
    }
    """
    rows = page.eval_on_selector_all("[data-testid], [role=textbox], input, textarea", js)
    print("=== URL-editor DOM ===")
    for r in rows:
        print(
            f"  [{r['kind']}] testid={r.get('testid','')!r} tag={r['tag']!r} role={r.get('role','')!r} "
            f"editable={r.get('contentEditable','')!r} placeholder={r.get('placeholder','')!r} "
            f"value={r.get('value','')!r} text={r['text']!r}"
        )
    print()


def _read_field(page, selector: str) -> Optional[str]:
    loc = page.locator(selector).first
    try:
        if loc.count() == 0:
            return None
    except Exception:
        return None
    # Try text_content (contenteditable) then value (plain input).
    txt: Optional[str] = None
    try:
        txt = loc.text_content()
        if txt is None:
            txt = ""
        if txt:
            return txt
    except Exception:
        pass
    try:
        return loc.get_attribute("value")
    except Exception:
        return txt


def _find_utm_selector(page) -> Optional[str]:
    """Discover the UTMInput testid by scanning the DOM."""
    js = r"""
    () => {
      const hits = [];
      document.querySelectorAll('[data-testid]').forEach(el => {
        const t = el.getAttribute('data-testid') || '';
        if (/UTM/i.test(t)) hits.push(t);
      });
      return hits;
    }
    """
    try:
        testids = page.eval_on_selector_all("[data-testid]", js)
    except Exception:
        return None
    if not testids:
        return None
    # Prefer a *.Textinput form (same family as LinkInput), else the UTMInput root.
    for t in testids:
        if "Textinput" in t:
            return f'[data-testid="{t}"]'
    return f'[data-testid="{testids[0]}"]'


def _read_baseline(page) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    link = _read_field(page, LINK_INPUT)
    utm_selector = _find_utm_selector(page)
    utm = _read_field(page, utm_selector) if utm_selector else None
    print(f"=== BASELINE (campaign {CAMPAIGN_ID}) ===")
    print(f"  UTMInput selector discovered: {utm_selector!r}")
    print(f"  LinkInput value: {link!r}")
    print(f"  UTMInput value:  {utm!r}")
    print()
    return link, utm, utm_selector


def _split_url(url: str) -> Tuple[str, str]:
    if "?" in url:
        bare, _, query = url.partition("?")
        return bare, query
    return url, ""


def _set_link_input(page, url: str) -> None:
    """Set the LinkInput field, bypassing _set_landing_url's archived guard.

    The guard checks Clear button disabled BEFORE clicking the field — but the
    button is disabled whenever the field isn't focused (not only when archived).
    We click the field first, then check, matching the real interaction order.
    """
    from direct_cli.browser.masters import (
        _EDIT_URL_INPUT_TESTID,
        _EDIT_URL_CLEAR_BUTTON_TESTID,
        _clear_text_field,
        _type_landing_url,
        _is_button_disabled,
    )
    from direct_cli.browser.session import BrowserSessionError

    field = page.locator(_EDIT_URL_INPUT_TESTID).first
    try:
        field.click()
    except Exception as exc:
        raise BrowserSessionError(f"Could not click LinkInput: {exc}") from exc
    page.wait_for_timeout(1000)

    clear_button = page.locator(_EDIT_URL_CLEAR_BUTTON_TESTID).first
    for _ in range(30):
        if not _is_button_disabled(clear_button):
            break
        page.wait_for_timeout(100)
    else:
        raise BrowserSessionError(
            "LinkInput Clear button is still disabled after click+poll — "
            "campaign may be ARCHIVED or the widget is stuck."
        )

    if not _clear_text_field(field):
        raise BrowserSessionError("Could not clear LinkInput")

    try:
        current = field.text_content()
    except Exception:
        current = None
    if current not in ("", None):
        raise BrowserSessionError(
            f"Could not clear LinkInput: still shows {current!r}"
        )

    if url:
        _type_landing_url(field, url)


def _set_link_input_js(page, url: str) -> None:
    """Set the LinkInput field via JS fill (for very long URLs that timeout
    on field.type())."""
    from direct_cli.browser.masters import (
        _EDIT_URL_INPUT_TESTID,
        _EDIT_URL_CLEAR_BUTTON_TESTID,
        _is_button_disabled,
    )
    from direct_cli.browser.session import BrowserSessionError

    field = page.locator(_EDIT_URL_INPUT_TESTID).first
    try:
        field.click()
    except Exception as exc:
        raise BrowserSessionError(f"Could not click LinkInput: {exc}") from exc
    page.wait_for_timeout(1000)

    clear_button = page.locator(_EDIT_URL_CLEAR_BUTTON_TESTID).first
    for _ in range(30):
        if not _is_button_disabled(clear_button):
            break
        page.wait_for_timeout(100)
    else:
        raise BrowserSessionError(
            "LinkInput Clear button is still disabled after click+poll"
        )

    # Use page.fill() which sets textContent directly (bypasses Combobox).
    field.fill(url)
    page.wait_for_timeout(300)


def _type_utm_input(page, selector: str, value: str) -> None:
    """Type into the UTMInput field (contenteditable, no suggestion popup)."""
    from direct_cli.browser.masters import _clear_text_field, _type_landing_url

    field = page.locator(selector).first
    field.click()
    page.wait_for_timeout(300)
    if value:
        # UTMInput is initially empty — no clear needed.
        _type_landing_url(field, value)
    else:
        # Clear if there's existing UTM content.
        _clear_text_field(field)


def _save(page) -> None:
    from direct_cli.browser.masters import _SAVE_BUTTON_TEXT

    btn = page.get_by_role("button", name=_SAVE_BUTTON_TEXT, exact=True).first
    try:
        btn.scroll_into_view_if_needed()
    except Exception:
        page.mouse.wheel(0, 20_000)
    btn.click()
    # Settle: wait for the save to commit, then reload the edit page and
    # settle again (convention #750 — reload+re-read, never trust the click).
    page.wait_for_timeout(2000)
    _wait_edit_form(page)
    page.wait_for_timeout(3000)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true",
                    help="Apply split test + restore (coordinated live window ONLY).")
    ap.add_argument("--headful", action="store_true")
    ap.add_argument("--test-url", default=None,
                    help="URL to use as the split test value when --mutate.")
    args = ap.parse_args()

    test_url = args.test_url or (
        "https://lp.ksamata.ru/test_recon_761?utm_source=recon761"
        "&utm_medium=cpc&utm_campaign={campaign_id}&utm_term={gbid}"
    )

    with _open_session(headless=not args.headful) as page:
        _wait_edit_form(page)
        page.wait_for_timeout(3000)

        # Read orig_link BEFORE expanding the spoiler (clean LinkInput read,
        # not disturbed by the spoiler's re-render).
        orig_link = _read_field(page, LINK_INPUT)
        expanded = _expand_advanced_params(page)
        print(f"=== 'Дополнительные параметры' spoiler expanded: {expanded} ===")
        print()
        if not expanded:
            page.wait_for_timeout(3000)
            expanded = _expand_advanced_params(page)
            print(f"=== retry spoiler expanded: {expanded} ===")
            print()
        utm_selector = UTM_INPUT if _read_field(page, UTM_INPUT) is not None else _find_utm_selector(page)
        orig_utm = _read_field(page, utm_selector) if utm_selector else None
        print(f"=== BASELINE (campaign {CAMPAIGN_ID}) ===")
        print(f"  LinkInput value: {orig_link!r}")
        print(f"  UTMInput value:  {orig_utm!r}  (selector={utm_selector!r})")
        print()

        if not args.mutate:
            print("Read-only recon complete (no mutation). Re-run with --mutate to test the split.")
            return 0

        if not utm_selector:
            print("ERROR: could not discover a UTMInput testid — cannot test split.")
            return 2

        bare, query = _split_url(test_url)
        print(f"=== MUTATION TEST ===")
        print(f"  test_url={test_url!r}")
        print(f"  -> LinkInput (bare) = {bare!r}")
        print(f"  -> UTMInput (query) = {query!r}")
        print(f"  original: LinkInput={orig_link!r} UTMInput={orig_utm!r}")
        print()

        # Apply split: bare -> LinkInput, query -> UTMInput.
        _set_link_input(page, bare)
        # Expand spoiler and type into UTMInput.
        if not _spoiler_expanded(page):
            _expand_advanced_params(page)
        _type_utm_input(page, utm_selector, query)
        # Ensure spoiler is still expanded before save (Yandex must see
        # UTMInput value at submit time).
        if not _spoiler_expanded(page):
            _expand_advanced_params(page)
        _save(page)

        after_link = _read_field(page, LINK_INPUT)
        if not _spoiler_expanded(page):
            _expand_advanced_params(page)
        after_utm = _read_field(page, utm_selector)
        print(f"=== AFTER SAVE+RELOAD ===")
        print(f"  LinkInput: {after_link!r}")
        print(f"  UTMInput:  {after_utm!r}")
        accepted = (after_link == bare) and (after_utm == query)
        print(f"  ACCEPTED (split saved as written): {accepted}")
        print()

        # Restore exact original state using JS fill (orig URL is too long
        # for field.type() — it would timeout).
        print(f"=== RESTORE ===")
        print(f"  restoring LinkInput={orig_link!r} UTMInput={orig_utm!r}")
        _set_link_input_js(page, orig_link or "")
        if not _spoiler_expanded(page):
            _expand_advanced_params(page)
        if orig_utm:
            _type_utm_input(page, utm_selector, "")
        _save(page)

        restored_link = _read_field(page, LINK_INPUT)
        if not _spoiler_expanded(page):
            _expand_advanced_params(page)
        restored_utm = _read_field(page, utm_selector) if utm_selector else None
        print(f"  restored LinkInput: {restored_link!r}")
        print(f"  restored UTMInput:  {restored_utm!r}")
        restored_ok = (restored_link == (orig_link or "")) and (
            restored_utm == (orig_utm or "")
        )
        print(f"  RESTORED to original: {restored_ok}")
        print()

        if not restored_ok:
            print("WARNING: restore did not match original — manual check needed:")
            print(f"  expected link={orig_link!r} utm={orig_utm!r}")
            print(f"  got     link={restored_link!r} utm={restored_utm!r}")
            return 3
        if not accepted:
            print("NOTE: split was NOT accepted by Yandex — hypothesis not confirmed.")
        return 0 if accepted else 1


if __name__ == "__main__":
    sys.exit(main())