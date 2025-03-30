import itertools
from dataclasses import dataclass

from ens import ENS
from flask import Blueprint
from sentry_sdk import capture_exception
from web3 import HTTPProvider, Web3

from remote.wrapper import APIError, error, success

ens_bp = Blueprint("ens", __name__)

w3 = Web3(HTTPProvider("https://eth.llamarpc.com"))
w3.provider.request_counter = itertools.count(start=1)


@dataclass
class ENSName:
    name: str
    owner: str = None


@ens_bp.route("/ens/<ens_name>")
def ens_query(ens_name):
    if not ens_name.endswith(".eth"):
        return error(
            APIError(message="Please provide a valid ENS name that ends with .eth")
        )
    try:
        ns = ENS.fromWeb3(w3)
        name = ENSName(name=ens_name)
        name.owner = ns.owner(name.name)
        return success(name)
    except Exception as e:  # noqa
        capture_exception(e)
        return error(
            APIError(
                message="Error occurred when communicating with the Ethereum network"
            ),
            status=404,
        )
