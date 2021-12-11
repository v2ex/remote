import time
from collections import namedtuple
from dataclasses import dataclass
from typing import List

import dns.resolver
import pyipip
from dns.exception import DNSException
from flask import Blueprint, current_app, request
from flask.helpers import is_ip
from sentry_sdk import capture_exception

from remote.wrapper import APIError, error, success

# Please keep the blueprint definition at the top uniformly.
network_bp = Blueprint("network", __name__)

_ipdb = None


def _get_ipdb():
    global _ipdb
    if not _ipdb:
        _ipdb = pyipip.IPIPDatabase(current_app.config["IPIP_DB_PATH"])
    return _ipdb


IPRecord = namedtuple(
    "IPRecord",
    [
        "status",
        "success",
        "country",
        "province",
        "city",
        "org",
        "isp",
        "latitude",
        "longitude",
        "timezone",
        "tz_diff",
        "cn_division_code",
        "calling_code",
        "country_code",
        "continent_code",
    ],
)


@network_bp.route("/ipip/<access_ip>")
def ipip(access_ip):
    if ":" in access_ip:
        return error(APIError(message="IPv6 is not supported"))

    if not is_ip(access_ip):
        return error(APIError(message="Invalid IPv4 address provided"))

    try:
        _db = _get_ipdb()
        ip_fields = _db.lookup(access_ip).split("\t")
        # Subtract the number of fields that we own assigned.
        except_ip_meta_length = len(IPRecord._fields) - 2
        ip_record = IPRecord("ok", True, *ip_fields[:except_ip_meta_length])
        return success(ip_record._asdict())
    except Exception as e:  # noqa
        capture_exception(e)
        return error(APIError(message="IP info not found"), status=404)


@dataclass
class UserIP:
    ip: str
    ipv4: str = None
    ipv6: str = None
    ipv4_available: bool = None
    ipv6_available: bool = None
    success: bool = True

    def __post_init__(self):
        """We will automatically calculate the remaining fields at this stage."""
        self.ipv4 = self.extract_ip4(self.ip) if self.is_ipv4 else None
        self.ipv6 = None if self.is_ipv4 else self.ip
        self.ipv4_available = self.is_ipv4
        self.ipv6_available = not self.is_ipv4

    @property
    def is_ipv4(self) -> bool:
        return "." in self.ip

    @staticmethod
    def extract_ip4(raw_ip: str) -> str:
        return raw_ip.replace("::ffff:", "")  # noqa


@network_bp.route("/ip")
def ip():
    _ip = request.remote_addr
    if forwarded := request.headers.get("X-Forwarded-For"):
        _ip = forwarded
    return success(UserIP(ip=_ip))


@dataclass
class ResolveResp:
    ttl: float
    answers: List
    nameservers: List[str]
    status: str = None
    success: bool = True

    def __post_init__(self):
        """We will automatically calculate the `statue` field at this stage."""
        self.status = "ok" if len(self.answers) > 0 else "error"


@network_bp.route("/dns/resolve")
def resolve():
    if not (domain := request.args.get("domain")):
        api_error = APIError(message='Required parameter "domain" is missing or empty')
        return error(api_error)

    local_resolver = dns.resolver.Resolver()
    nameservers = current_app.config["NAMESERVERS"]
    local_resolver.nameservers = nameservers
    try:
        dns_answer = local_resolver.resolve(domain)
    except DNSException:
        return error(
            APIError(message=f"Unable to resolve the specified domain: {domain}")
        )

    resolve_resp = ResolveResp(
        nameservers=nameservers,
        ttl=dns_answer.expiration - time.time(),
        answers=[rrset.to_text() for rrset in dns_answer],
    )
    return success(resolve_resp)
