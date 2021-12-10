#! /usr/bin/env python
# -*- coding: utf-8 -*-

import logging
import subprocess


def _curl_download(domain: str, ip: str, https: bool = True) -> int:
    schema = "https" if https else "http"
    port = "443" if https else "80"
    url = f"{domain}:{port}:{ip}"
    target = f"{schema}://{url}"

    return subprocess.call(
        [
            "/usr/bin/curl",
            "-v",
            "-o",
            "/dev/null",
            "--resolve",
            url,
            target,
        ],
        shell=False,
    )


def curl_download(ip, domain, uri, https):
    http_result = _curl_download(domain, ip, https=False)
    resp = "success" if http_result == 0 else "failed"
    logging.info("HTTP Download %s: %s %s", resp, domain, uri)

    https_result = None
    if https == "yes":
        https_result = _curl_download(domain, ip, https=True)
        resp = "success" if https_result == 0 else "failed"
        logging.info("HTTPS Download %s: %s %s", resp, domain, uri)
    return http_result, https_result
