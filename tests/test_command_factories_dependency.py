"""Dependency-substitution parity for the shared command factories.

Epic #961, track 7: the ``get``/``set-bids``/lifecycle command factories
capture their command module's ``create_client`` symbol at registration
(import) time, so the live path must re-read it from the module
(:func:`direct_cli.api.resolve_module_create_client`) for a
``patch("direct_cli.commands.<module>.create_client")`` to intercept. This
test walks the registered CLI tree and asserts, for every resource group
that has both a factory ``get`` and a factory lifecycle command, that the
SUBSTITUTED factory is the one actually used by both commands, and that
each reaches it with its documented request shape — the same behaviour
under dependency substitution, not just the same registration.

Hand-rolled ``get`` commands (``leads``, ``keywordbids``, ``ads``,
``campaigns``, ``reports``) are covered by their own per-module suites;
groups whose ``get`` takes no ``--ids`` option (e.g. ``agencyclients``
filters by ``--logins``) are skipped here because this probe invokes the
shared flag surface only.
"""

import click
import importlib
from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from direct_cli.cli import cli

LIFECYCLE_METHODS = (
    "delete",
    "suspend",
    "resume",
    "archive",
    "unarchive",
    "moderate",
)

# Not factory-built lifecycle commands, deliberately outside this probe:
# - adgroups suspend/resume are composite emulations via ads.get +
#   ads.suspend/ads.resume (issue #573), with their own module-level client
#   reads;
# - v4* groups use the v4 client factory (create_v4_client), a different
#   dependency surface covered by the v4 suites.
NON_FACTORY_CASES = {
    ("adgroups", "suspend"),
    ("adgroups", "resume"),
}


def _dependency_parity_cases():
    """(group name, lifecycle method) pairs for groups with factory get+lifecycle."""
    cases = []
    for name, group in cli.commands.items():
        if not isinstance(group, click.Group):
            continue
        if name.startswith("v4"):
            continue
        if "get" not in group.commands:
            continue
        for method in LIFECYCLE_METHODS:
            if method in group.commands and (name, method) not in NON_FACTORY_CASES:
                cases.append((name, method))
    return cases


def _ids_option(command):
    for param in command.params:
        if param.name == "ids":
            return param
    return None


def _invoke_lifecycle_id(command):
    """The CLI flag/value pair a lifecycle command needs for one object."""
    id_param = next(param for param in command.params if param.required)
    flag = id_param.opts[0]
    if isinstance(id_param.type, (click.types.IntParamType, click.types.IntRange)):
        return flag, "1"
    return flag, "test-hash"


@pytest.mark.parametrize(
    "group_name,method",
    _dependency_parity_cases(),
    ids=lambda *a: "-".join(map(str, a)),
)
def test_substituted_create_client_intercepts_get_and_lifecycle(group_name, method):
    group = cli.commands[group_name]
    assert isinstance(group, click.Group)
    module = importlib.import_module(group.callback.__module__)
    if not hasattr(module, "create_client"):
        pytest.fail(f"{group_name}: no module-level create_client to substitute")
    get_command = group.commands["get"]
    if _ids_option(get_command) is None:
        pytest.skip("get has no --ids option (custom criteria surface)")

    extract_obj = Mock()
    extract_obj.extract.return_value = {"Id": 7}
    extract_obj.iter_items.return_value = iter([{"Id": 7}])
    fake_client = Mock()
    service = getattr(fake_client, group_name)
    service.return_value.post.return_value = Mock(return_value=extract_obj)
    substituted_factory = Mock(return_value=fake_client)

    runner = CliRunner()
    with patch_module_create_client(module, substituted_factory):
        # The get path resolves the substituted factory and posts through it.
        result = runner.invoke(cli, [group_name, "get", "--ids", "1"])
        assert result.exit_code == 0, result.output
        get_body = service.return_value.post.call_args.kwargs["data"]
        assert get_body["method"] == "get"
        assert substituted_factory.called

        # The lifecycle path must behave identically under the same
        # substitution: same factory instance, documented request shape.
        lifecycle_command = group.commands[method]
        flag, value = _invoke_lifecycle_id(lifecycle_command)
        result = runner.invoke(cli, [group_name, method, flag, value])
        assert result.exit_code == 0, result.output
        lifecycle_body = service.return_value.post.call_args.kwargs["data"]
        assert lifecycle_body["method"] == method
        criteria = lifecycle_body["params"]["SelectionCriteria"]
        assert criteria, "lifecycle request must carry SelectionCriteria"
        substituted_factory.assert_called()

    # The real factory must be restored after the patch window.
    assert module.create_client is not substituted_factory


def patch_module_create_client(module, factory):
    import unittest.mock

    return unittest.mock.patch.object(module, "create_client", factory)
