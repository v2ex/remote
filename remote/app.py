#! /usr/bin/env python
# -*- coding: utf-8 -*-

import logging
from typing import Union

import sentry_sdk
from flask import Flask
from sentry_sdk.integrations.flask import FlaskIntegration

from remote.blueprints import image_bp, index_bp, network_bp
from remote.utilities import load_module


def init_sentry(dsn: str, env: str = None):
    sentry_sdk.init(
        dsn=dsn,
        integrations=[FlaskIntegration()],
        environment=env,
        # Set traces_sample_rate to 1.0 to capture 100%
        # of transactions for performance monitoring.
        # We recommend adjusting this value in production.
        traces_sample_rate=1.0,
        # By default, the SDK will try to use the SENTRY_RELEASE
        # environment variable, or infer a git commit
        # SHA as release, however you may want to set
        # something more human-readable.
        # release="myapp@1.0.0",
    )


def load_config(flask_app: Flask, config: Union[object, str]):
    # TODO !! load default config file first, then load others according to env.
    try:
        flask_app.config.from_object(config)
    except Exception:  # noqa
        module = load_module("config", "remote/config.example.py")
        flask_app.config.from_object(module)


def setup_logger(flask_app: Flask):
    # Default log level: `DEBUG` if app is running on debug/test mode, `INFO` otherwise.
    # If `LOG_LEVEL` is actively set in the configuration, the set value shall prevail.
    _loger = logging.getLogger(flask_app.name)

    level = logging.INFO
    if flask_app.debug or flask_app.testing:
        level = logging.DEBUG
    level = flask_app.config.get("LOG_LEVEL", level)
    _loger.setLevel(level)
    # TODO set logger format


def register_blueprint(flask_app: Flask):
    # TODO consider configuring each blueprint with its own `url_prefix`.
    blueprints = [
        index_bp,
        image_bp,
        network_bp,
    ]
    for bp in blueprints:
        flask_app.register_blueprint(bp)


def create_app(config: Union[object, str] = "remote.config", name: str = None) -> Flask:
    _app_name = name or __name__

    _app = Flask(_app_name)

    # Load config from python module.
    # Make sure to load the configuration before other actions.
    # In case others from relying on the configuration.
    load_config(_app, config)

    # Setup logger for whole app.
    setup_logger(_app)

    # Register all blueprints.
    register_blueprint(_app)

    # Init sentry.
    init_sentry(_app.config["SENTRY_DSN"], _app.config["SENTRY_ENVIRONMENT"])

    # Since flask has built-in logging module(based on python native lib `logging`),
    # we use this(`Flask.logger`) instead of others(`logging`/`print`/...)
    # to print logs within the whole project.
    _app.logger.info(
        "Flask app `%s` created! running on `%s` env, debug: `%s`",
        _app.name,
        _app.config["ENV"],
        _app.config["DEBUG"],
    )

    return _app


app: Flask = create_app()


if __name__ == "__main__":
    app.run()
