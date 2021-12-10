from unittest.mock import patch

from remote.scripts.tasks import curl_download


def test_curl_download():
    download_func = "remote.scripts.tasks.subprocess.call"

    test_ip = "127.0.0.1"
    test_domain = "com.example"
    test_uri = "/test"

    with patch(download_func, return_value=0):
        resp = curl_download(test_ip, test_domain, test_uri, "yes")
        assert resp == (0, 0)

    with patch(download_func, return_value=0):
        resp = curl_download(test_ip, test_domain, test_uri, "no")
        assert resp == (0, None)

    with patch(download_func, return_value=1):
        resp = curl_download(test_ip, test_domain, test_uri, "yes")
        assert resp == (1, 1)

    with patch(download_func, return_value=1):
        resp = curl_download(test_ip, test_domain, test_uri, "no")
        assert resp == (1, None)
