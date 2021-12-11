from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum, unique
from functools import partial, wraps
from typing import Any

from flask import Response, json, request


@unique
class Methods(Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    ...

    @classmethod
    def common(cls):
        return [cls.GET.value, cls.POST.value]


@dataclass
class APIDoc:
    usage: str
    status: str = "ok"
    success: bool = True


def api_doc(doc: APIDoc):
    """To decorate the `get` method to return the description of the API."""

    def wrapper(func):
        @wraps(func)
        def inner(*args, **kwargs):
            if request.method == Methods.GET.value:
                return success(doc)

            return func(*args, **kwargs)

        return inner

    return wrapper


@dataclass
class APIError:
    message: str
    status: str = "error"
    success: bool = False


@unique
class MIMEType(Enum):
    HTML = "text/html;charset=utf-8"
    PLAIN = "text/plain;charset=utf-8"
    JSON = "application/json;charset=utf-8"
    XML = "application/xml;charset=utf-8"
    ...


def _response(content: Any, status: int, mime_type: MIMEType = MIMEType.JSON, **kwargs):
    if is_dataclass(content):
        content = json.dumps(asdict(content))
    elif isinstance(content, dict):
        content = json.dumps(content)
    return Response(response=content, status=status, mimetype=mime_type.value, **kwargs)


# Shortcut for error response with default http code 400.
#   - return json to user:
#       ```
#       return error({"status": "error", "message": "..."})
#       ```
#   - return dataclass to user:
#       Sometimes we use a simple dataclass instance(eg: `APIError`) to define
#       response data, it's simple and not easily to make spelling mistakes,
#       we will automatically package and process the data for you.
#       ```
#       return error(`SimpleDataclassInstance`, status=403)
#       ```
#   - return anything else to user:
#       ```
#       return error("Forbidden", status=401)
#       ```
error = partial(_response, status=400)

# Shortcut for success response with default http code 200,
# like `error` above, but it's for success response.
success = partial(_response, status=200)
