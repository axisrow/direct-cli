"""Yandex Direct API v4 Live (JSON) client adapter.

v4 Live exposes a single RPC endpoint at ``/live/v4/json/``. Unlike v5, the
operation name is carried in the JSON body (``method`` field) and errors are
reported with HTTP 200 plus a non-zero ``error_code`` in the body.

This adapter mirrors the shape of ``YandexDirectClientAdapter`` (v5) so that
the public API surface stays familiar — only the wire details differ.
"""

import logging
import time
from typing import Optional, Union

import orjson
from requests import Response
from tapi2 import JSONAdapterMixin, TapiAdapter, generate_wrapper_from_adapter
from tapi2.exceptions import ClientError, ResponseProcessException, TapiException

from .. import exceptions
from .resource_mapping import (
    RESOURCE_MAPPING_V4_LIVE,
    SUPPORTED_V4_METHODS,
)

logger = logging.getLogger(__name__)


class V4LiveClientAdapter(JSONAdapterMixin, TapiAdapter):
    resource_mapping = RESOURCE_MAPPING_V4_LIVE

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def get_api_root(self, api_params: dict, resource_name: str) -> str:
        if api_params.get("is_sandbox"):
            return "https://api-sandbox.direct.yandex.ru/"
        return "https://api.direct.yandex.ru/"

    def get_request_kwargs(self, api_params: dict, *args, **kwargs) -> dict:
        params = super().get_request_kwargs(api_params, *args, **kwargs)

        token = api_params.get("access_token")
        login = api_params.get("login")
        language = api_params.get("language", "en")
        finance_token = api_params.get("finance_token")
        operation_num = api_params.get("operation_num")

        # Enrich the JSON body with top-level v4 Live fields.
        # format_data_to_request does not see api_params, so we do this here,
        # after super() has already serialised the user data. Agency/client
        # selection is transport-level (Client-Login header); method params
        # must stay schema-shaped.
        raw = params.get("data")
        if raw:
            if isinstance(raw, (bytes, bytearray)):
                body = orjson.loads(raw)
            else:
                body = dict(raw)

            method = body.get("method")
            if method and method not in SUPPORTED_V4_METHODS:
                raise ValueError(
                    "Unknown v4 Live method: {!r}. Supported methods: {}".format(
                        method, sorted(SUPPORTED_V4_METHODS)
                    )
                )

            if token:
                body.setdefault("token", token)
            if language:
                body.setdefault("locale", language)
            if finance_token:
                body.setdefault("finance_token", finance_token)
            if operation_num is not None:
                body.setdefault("operation_num", operation_num)

            params["data"] = orjson.dumps(body)

        if token:
            params["headers"]["Authorization"] = "Bearer {}".format(token)

        if login:
            params["headers"]["Client-Login"] = login

        return params

    def format_data_to_request(self, data) -> Optional[bytes]:
        if data:
            return orjson.dumps(data)

    def response_to_native(self, response: Response) -> Union[dict, str, None]:
        if response.content.strip():
            try:
                return orjson.loads(response.content)
            except ValueError:
                return response.text

    def get_error_message(self, data, response=None):
        # v4 Live errors live at the top level of the body — return the whole
        # dict (with error_code/error_str/error_detail). The default
        # JSONAdapterMixin pulls data["error"], which is wrong for v4.
        if data is None and response is not None and response.content.strip():
            try:
                data = orjson.loads(response.content)
            except ValueError:
                data = None
        return data

    def process_response(self, response: Response, request_kwargs: dict, **kwargs) -> dict:
        # Mirror the v5 behaviour: turn the serialised body back into a dict so
        # downstream hooks (extract, retry) can read it.
        if isinstance(request_kwargs.get("data"), (bytes, bytearray, str)):
            request_kwargs["data"] = orjson.loads(request_kwargs["data"])

        if response.status_code == 502:
            raise exceptions.YandexDirectApiError(
                response, "v4 Live: server returned 502", **kwargs
            )

        data = self.response_to_native(response)

        # v4 Live returns HTTP 200 even on errors — detect via error_code.
        # Defensive cast: matches the pattern used in error_handling /
        # retry_request below, so a malformed error_code (null, string)
        # never raises a raw TypeError up through the adapter.
        if isinstance(data, dict):
            try:
                code = int(data.get("error_code", 0))
            except (TypeError, ValueError):
                code = 0
            if code != 0:
                raise ResponseProcessException(ClientError, data)

        return super().process_response(response, request_kwargs, **kwargs)

    def error_handling(
        self,
        tapi_exception: TapiException,
        error_message,
        repeat_number: int,
        response: Response,
        request_kwargs: dict,
        api_params: dict,
        **kwargs,
    ) -> None:
        code = 0
        if isinstance(error_message, dict):
            try:
                code = int(error_message.get("error_code", 0))
            except (TypeError, ValueError):
                code = 0

        if code == 53:
            raise exceptions.V4LiveTokenError(response, error_message, **kwargs)
        if code in (54, 55, 56):
            raise exceptions.V4LiveRequestsLimitError(response, error_message, **kwargs)
        raise exceptions.V4LiveError(response, error_message, **kwargs)

    def retry_request(
        self,
        tapi_exception: TapiException,
        error_message,
        repeat_number: int,
        response: Response,
        request_kwargs: dict,
        api_params: dict,
        **kwargs,
    ) -> bool:
        code = 0
        if isinstance(error_message, dict):
            try:
                code = int(error_message.get("error_code", 0))
            except (TypeError, ValueError):
                code = 0

        if code in (54, 55) and api_params.get("retry_if_exceeded_limit", True):
            logger.warning("v4 Live limit exceeded (code=%s), retry in 10s", code)
            time.sleep(10)
            return True

        if code in (52, 1000, 1001, 1002) or response.status_code == 500:
            if repeat_number < api_params.get("retries_if_server_error", 5):
                logger.warning("v4 Live server error (code=%s), retry in 1s", code)
                time.sleep(1)
                return True

        return False

    def extract(self, data, response: Optional[Response] = None,
                request_kwargs: Optional[dict] = None, **kwargs):
        # v4 Live always nests payload under "data". For methods returning a
        # bare scalar (TransferMoney → 1), the scalar comes through unchanged.
        # response / request_kwargs are accepted but unused — they are kept
        # only so the tapi2 framework can pass them positionally from
        # YandexDirectClientResponse.extract(). Iterator hooks
        # (get_iterator_pages / _items / _iteritems) call extract via **kwargs
        # without these arguments, so defaults are required.
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        return data

    def get_iterator_next_request_kwargs(
        self,
        response_data,
        response: Response,
        request_kwargs: dict,
        api_params: dict,
        **kwargs,
    ):
        # v4 Live has no uniform pagination — each method (GetEventsLog,
        # GetWordstatReportList, ...) paginates with its own params. The
        # adapter performs single-shot requests; helpers can be added later.
        return None

    def get_iterator_pages(self, response_data, **kwargs):
        return [self.extract(response_data, **kwargs)]

    def get_iterator_items(self, data, **kwargs):
        if isinstance(data, dict) and "data" in data:
            return self.extract(data, **kwargs)
        return data

    def get_iterator_iteritems(self, response_data, **kwargs):
        return self.extract(response_data, **kwargs)


YandexDirectV4Live = generate_wrapper_from_adapter(V4LiveClientAdapter)
