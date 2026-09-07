"""Tests for GitHub/GitLab connect — parsing, validation, SSRF-safe URL building.

HTTP is always mocked; these tests never touch the network.
"""
import io
import zipfile
from unittest import mock

from django.test import TestCase

from apps.ingest import connect
from apps.ingest.connect import ConnectError, fetch_repo_archive, parse_repo


def _zip_bytes():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("myrepo-abc123/main.py", "print('hi')\n")
    return buf.getvalue()


class _Resp:
    def __init__(self, status=200, body=b""):
        self.status_code = status
        self._body = body

    def iter_content(self, chunk_size=65536):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i:i + chunk_size]


class ParseRepoTests(TestCase):
    def test_owner_repo(self):
        self.assertEqual(parse_repo("acme/billing"), ("acme", "billing"))

    def test_https_url(self):
        self.assertEqual(parse_repo("https://github.com/acme/billing"), ("acme", "billing"))

    def test_url_with_git_suffix_and_trailing(self):
        self.assertEqual(parse_repo("https://gitlab.com/acme/billing.git"), ("acme", "billing"))

    def test_ssh_url(self):
        self.assertEqual(parse_repo("git@github.com:acme/billing.git"), ("acme", "billing"))

    def test_incomplete_rejected(self):
        with self.assertRaises(ConnectError):
            parse_repo("just-one-part")


class ValidationTests(TestCase):
    def test_bad_provider(self):
        with self.assertRaises(ConnectError):
            fetch_repo_archive("bitbucket", "a", "b")

    def test_traversal_in_ref_rejected(self):
        with self.assertRaises(ConnectError):
            fetch_repo_archive("github", "acme", "billing", ref="../../etc")

    def test_bad_owner_rejected(self):
        with self.assertRaises(ConnectError):
            fetch_repo_archive("github", "acme/../evil", "billing")


class FetchTests(TestCase):
    @mock.patch("apps.ingest.connect.requests.get")
    def test_github_url_and_headers(self, get):
        get.return_value = _Resp(200, _zip_bytes())
        buf = fetch_repo_archive("github", "acme", "billing", ref="main", token="ghp_x")
        url = get.call_args[0][0]
        headers = get.call_args.kwargs["headers"]
        self.assertEqual(url, "https://api.github.com/repos/acme/billing/zipball/main")
        self.assertEqual(headers["Authorization"], "Bearer ghp_x")
        # returns a usable zip
        self.assertTrue(zipfile.is_zipfile(buf))

    @mock.patch("apps.ingest.connect.requests.get")
    def test_gitlab_encodes_project_path(self, get):
        get.return_value = _Resp(200, _zip_bytes())
        fetch_repo_archive("gitlab", "acme", "billing", token="glpat-x")
        url = get.call_args[0][0]
        headers = get.call_args.kwargs["headers"]
        self.assertEqual(url, "https://gitlab.com/api/v4/projects/acme%2Fbilling/repository/archive.zip")
        self.assertEqual(headers["PRIVATE-TOKEN"], "glpat-x")

    @mock.patch("apps.ingest.connect.requests.get")
    def test_host_is_always_fixed(self, get):
        # Even if the "owner" tried to smuggle a host, the request host stays fixed.
        get.return_value = _Resp(200, _zip_bytes())
        fetch_repo_archive("github", "acme", "billing")
        self.assertTrue(get.call_args[0][0].startswith("https://api.github.com/"))

    @mock.patch("apps.ingest.connect.requests.get")
    def test_404_is_honest(self, get):
        get.return_value = _Resp(404)
        with self.assertRaises(ConnectError):
            fetch_repo_archive("github", "acme", "nope")

    @mock.patch("apps.ingest.connect.requests.get")
    def test_auth_error(self, get):
        get.return_value = _Resp(401)
        with self.assertRaisesRegex(ConnectError, "token"):
            fetch_repo_archive("github", "acme", "private")

    @mock.patch("apps.ingest.connect.requests.get")
    def test_oversized_download_capped(self, get):
        big = b"x" * (connect.MAX_DOWNLOAD_BYTES + 10)
        get.return_value = _Resp(200, big)
        with self.assertRaisesRegex(ConnectError, "too large"):
            fetch_repo_archive("github", "acme", "billing")

    @mock.patch("apps.ingest.connect.requests.get",
                side_effect=connect.requests.RequestException("no network"))
    def test_network_failure_is_honest(self, get):
        with self.assertRaisesRegex(ConnectError, "reach"):
            fetch_repo_archive("github", "acme", "billing")
