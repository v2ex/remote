import time
from dataclasses import dataclass, field

from flask import Blueprint, current_app

from remote.wrapper import success

# Please keep the blueprint definition at the top uniformly.
index_bp = Blueprint("index", __name__)

_started = time.time()


@index_bp.route("/")
def home():
    return success({})


@dataclass
class Pong:
    status: str = "ok"
    message: str = "pong"
    uptime: float = field(default_factory=lambda: time.time() - _started)
    success: bool = True


@index_bp.route("/ping")
def ping():
    return success(Pong())


@dataclass
class WorkerInfo:
    status: str = "ok"
    uid: str = field(default_factory=lambda: current_app.config["UID"])
    uptime: float = field(default_factory=lambda: time.time() - _started)
    country: str = field(default_factory=lambda: current_app.config["COUNTRY"])
    region: str = field(default_factory=lambda: current_app.config["REGION"])
    success: bool = True


@index_bp.route("/hello")
def hello():
    return success(WorkerInfo())
