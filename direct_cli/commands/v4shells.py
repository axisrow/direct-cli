"""Shell command groups for Yandex Direct v4 Live command families."""

import click

V4_EPILOG = (
    "\b\n"
    "V4 Live commands use typed flags only. Supported methods are listed in "
    "the Yandex Direct v4 Live documentation: "
    "https://yandex.com/dev/direct/doc/dg-v4/en/live/concepts"
)


@click.group(epilog=V4_EPILOG)
def v4finance():
    """Yandex Direct v4 Live finance commands."""


@click.group(epilog=V4_EPILOG)
def v4account():
    """Yandex Direct v4 Live account commands."""


@click.group(epilog=V4_EPILOG)
def v4events():
    """Yandex Direct v4 Live events commands."""


@click.group(epilog=V4_EPILOG)
def v4wordstat():
    """Yandex Direct v4 Live wordstat commands."""


@click.group(epilog=V4_EPILOG)
def v4forecast():
    """Yandex Direct v4 Live forecast commands."""


@click.group(epilog=V4_EPILOG)
def v4meta():
    """Yandex Direct v4 Live metadata commands."""
