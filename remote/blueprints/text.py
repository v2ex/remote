import re

import bleach
from bs4 import BeautifulSoup
from flask import Blueprint, request
from marko.ext.gfm import gfm
from sentry_sdk import capture_exception

from remote.wrapper import APIDoc, APIError, Methods, api_doc, error, success

text_bp = Blueprint("text", __name__)

MARKDOWN_TAGS = [
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "b",
    "i",
    "strong",
    "em",
    "tt",
    "del",
    "p",
    "br",
    "span",
    "div",
    "blockquote",
    "code",
    "hr",
    "pre",
    "ul",
    "ol",
    "li",
    "dd",
    "dt",
    "img",
    "table",
    "thead",
    "tr",
    "th",
    "td",
    "tbody",
    "a",
    "input",
]

MARKDOWN_ATTRS = {
    "img": ["src", "alt", "title"],
    "a": ["href", "alt", "title"],
    "code": ["class"],
    "input": ["disabled", "type"],
}


def get_input_text() -> APIError | str:
    input_json = request.get_json()
    if not input_json:
        return APIError(message="Invalid input")
    if "text" in input_json:
        return input_json["text"]
    else:
        return APIError(message="Missing text input")


def __mentions(value):
    if value is not None:
        return re.sub(
            r"(\A|\s|[\u4e00-\u9fa5])@([\w\-\_]+)",
            r'\1@<a href="/member/\2">\2</a>',
            value,
        )
    else:
        return value


def __render_markdown(text: str) -> str:
    text = bleach.linkify(
        bleach.clean(gfm(text), MARKDOWN_TAGS, MARKDOWN_ATTRS), skip_tags=["pre"]
    )
    soup = BeautifulSoup(text, "html.parser")
    # Add class="embedded_image" referrerpolicy="no-referrer" rel="noreferrer" to img
    for img in soup.find_all("img"):
        img["class"] = "embedded_image"
        img["referrerpolicy"] = "no-referrer"
        img["rel"] = "noreferrer"
        img["loading"] = "lazy"
    for p in soup.find_all("p"):
        if p.string is not None and "@" in p.string:
            p.replace_with(
                BeautifulSoup("<p>" + __mentions(p.string) + "</p>", "html.parser")
            )
    return str(soup)


@text_bp.route("/text/render_markdown", methods=Methods.common())
@api_doc(
    APIDoc(
        usage="Upload a piece of text in the Markdown format and render it into HTML"
    )
)
def render_markdown():
    text_input = get_input_text()
    if isinstance(text_input, APIError):
        return error(text_input)
    try:
        text_output = __render_markdown(text=text_input)
    except Exception as e:  # noqa
        capture_exception(e)
        return error(APIError(message="Failed to render markdown"))
    return success(
        {
            "status": "ok",
            "success": True,
            "message": "Successfully rendered Markdown",
            "input": text_input,
            "output": text_output,
        }
    )
