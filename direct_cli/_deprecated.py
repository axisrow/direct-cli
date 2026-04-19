import click

DEPRECATED_ENTRYPOINT_MESSAGE = (
    "direct-cli is deprecated; use direct instead of direct-cli."
)


def deprecated_main() -> None:
    """Fail fast for the deprecated `direct-cli` entrypoint."""
    click.echo(f"Error: {DEPRECATED_ENTRYPOINT_MESSAGE}", err=True)
    raise SystemExit(2)
