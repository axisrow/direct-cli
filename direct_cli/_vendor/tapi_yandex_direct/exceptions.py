from typing import Dict, Union

from requests import Response
from tapi2.tapi import TapiClient


class YandexDirectApiError(Exception):
    def __init__(
        self,
        response: Response,
        data: Union[str, dict],
        client: TapiClient,
        *args,
        **kwargs
    ):
        self.response = response
        self.data = data
        self.client = client

    def __str__(self):
        return "{} {} {}\nHEADERS = {}\nURL = {}".format(
            self.response.status_code,
            self.response.reason,
            self.data or self.response.text,
            self.response.headers,
            self.response.url,
        )


class YandexDirectClientError(YandexDirectApiError):
    def __init__(
        self,
        response: Response,
        message: Dict[str, dict],
        client: TapiClient,
        *args,
        **kwargs
    ):
        self.error_code = message["error"]["error_code"]
        self.request_id = message["error"]["request_id"]
        self.error_string = message["error"]["error_string"]
        self.error_detail = message["error"]["error_detail"]
        super().__init__(response, message, client, *args, **kwargs)

    def __str__(self):
        text = "request_id={}, error_code={}, error_string={}, error_detail={}"

        return text.format(
            self.request_id, self.error_code, self.error_string, self.error_detail
        )


class YandexDirectTokenError(YandexDirectClientError):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class YandexDirectNotEnoughUnitsError(YandexDirectClientError):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class YandexDirectRequestsLimitError(YandexDirectClientError):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class V4LiveError(YandexDirectApiError):
    """Base exception for v4 Live API errors (error_code != 0).

    v4 Live error payload differs from v5: integer ``error_code``, ``error_str``
    instead of ``error_string``, no ``request_id``. Errors are returned with
    HTTP 200 — they are detected from the response body, not the status code.
    """

    def __init__(
        self,
        response: Response,
        message: Union[str, dict],
        client: TapiClient,
        *args,
        **kwargs,
    ):
        if isinstance(message, dict):
            try:
                self.error_code = int(message.get("error_code", 0))
            except (TypeError, ValueError):
                self.error_code = 0
            self.error_str = message.get("error_str", "")
            self.error_detail = message.get("error_detail", "")
        else:
            self.error_code = 0
            self.error_str = str(message)
            self.error_detail = ""
        super().__init__(response, message, client, *args, **kwargs)

    def __str__(self):
        return "v4 Live error_code={}, error_str={}, error_detail={}".format(
            self.error_code, self.error_str, self.error_detail
        )


class V4LiveTokenError(V4LiveError):
    """v4 Live error_code=53 — invalid or missing OAuth token."""


class V4LiveRequestsLimitError(V4LiveError):
    """v4 Live error_code in (54, 55, 56) — rate / method limit exceeded."""


class BackwardCompatibilityError(Exception):
    def __init__(self, name):
        self.name = name

    def __str__(self):
        return (
            "This {} is deprecated and not supported. "
            "Install a later version "
            "'pip install --upgrade tapi-yandex-direct==2020.12.15'. "
            "Info https://github.com/pavelmaksimov/tapi-yandex-direct"
        ).format(self.name)
