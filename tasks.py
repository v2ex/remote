#!/usr/bin/env python
# coding=utf-8

import logging
import subprocess


def curl_download(ip, domain, uri, https):
    target_http = "http://" + domain + uri
    target_https = "https://" + domain + uri
    r = subprocess.call(
        [
            "/usr/bin/curl",
            "-v",
            "-o",
            "/dev/null",
            "--resolve",
            domain + ":80:" + ip,
            target_http,
        ],
        shell=False,
    )
    if r == 0:
        logging.info(
            "HTTP Download success: {target_http}", extra={"target_http": target_http}
        )
    else:
        logging.error(
            "HTTP Download failed: {target_http}", extra={"target_http": target_http}
        )
    if https == "yes":
        r = subprocess.call(
            [
                "/usr/bin/curl",
                "-v",
                "-o",
                "/dev/null",
                "--resolve",
                domain + ":443:" + ip,
                target_https,
            ],
            shell=False,
        )
        if r == 0:
            logging.info(
                "HTTPS Download success: {target_https}",
                extra={"target_https": target_https},
            )
        else:
            logging.error(
                "HTTPS Download failed: {target_https}",
                extra={"target_https": target_https},
            )
