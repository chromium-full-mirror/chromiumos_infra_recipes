# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import base64
import subprocess
import unittest
from unittest import mock
import urllib.parse

import googleapiclient.discovery

import git
import gmail
import test_util


class TestGmailAnnouncer(unittest.TestCase):

  def setUp(self):
    super().setUp()

    # There can be long diffs in the expected vs. actual emails, so remove the
    # diff limit.
    self.maxDiff = None

    pending_changes = [
        git.Commit(
            '123',
            'author@gmail.com',
            'Commit 1',
            '2 days ago',
            '2020-01-02T12:00:00+00:00',
        ),
        git.Commit(
            '456',
            'author@gmail.com',
            'Commit 2',
            '3 days ago',
            '2020-01-01T12:00:00+00:00',
        )
    ]

    self._announcer = gmail.GmailAnnouncer(
        pending_changes=pending_changes,
        bundle_longname='test bundle',
        recipients=[
            'recipes-announce1@gmail.com', 'recipes-announce2@gmail.com'
        ],
        bccs=['recipes-bcc1@gmail.com', 'recipes-bcc2@gmail.com'],
        quota_project='test-cloud-project',
    )

    self._expected_body = '''
We've deployed Recipes (for test bundle) to prod!

Here is a summary of the changes:

*  123  [author@gmail.com]  Commit 1
*  456  [author@gmail.com]  Commit 2
'''

  @mock.patch.object(subprocess, 'run', autospec=True)
  def test_get_email_link(self, subprocess_mock):
    subprocess_mock.return_value = test_util.subprocess_stdout(
        'Mon Jul 24 08:29:35 PM UTC 2023')

    url_components = urllib.parse.urlparse(self._announcer.get_email_link())
    query_dict = urllib.parse.parse_qs(url_components.query)
    expected_query_dict = {
        'bcc': ['recipes-bcc1@gmail.com,recipes-bcc2@gmail.com'],
        'body': [self._expected_body],
        'fs': ['1'],
        'su': ['Recipes Release - Mon Jul 24 08:29:35 PM UTC 2023'],
        'to': ['recipes-announce1@gmail.com,recipes-announce2@gmail.com'],
        'view': ['cm']
    }
    self.assertDictEqual(expected_query_dict, query_dict)

  @mock.patch.object(googleapiclient.discovery, 'build', autospec=True)
  @mock.patch.object(subprocess, 'run', autospec=True)
  def test_send_email(self, subprocess_mock, discovery_mock):
    subprocess_mock.side_effect = [
        test_util.subprocess_stdout('luciauthtoken'),
        test_util.subprocess_stdout('Mon Jul 24 08:29:35 PM UTC 2023'),
    ]
    send_mock = mock.MagicMock()
    execute_mock = mock.MagicMock()
    discovery_mock.return_value.users.return_value.messages.return_value.send = send_mock
    send_mock.return_value.execute = execute_mock

    self._announcer.send_email()

    send_mock.assert_called_once()
    execute_mock.assert_called_once()

    expected_message = f'''
Content-Type: text/plain; charset="utf-8"
Content-Transfer-Encoding: 7bit
MIME-Version: 1.0
To: recipes-announce1@gmail.com, recipes-announce2@gmail.com
Bcc: recipes-bcc1@gmail.com, recipes-bcc2@gmail.com
Subject: Recipes Release - Mon Jul 24 08:29:35 PM UTC 2023


{self._expected_body.lstrip()}'''.lstrip()

    message = base64.b64decode(send_mock.call_args[1]['body']['raw']).decode()
    self.assertEqual(message, expected_message)

  @mock.patch.object(subprocess, 'run', autospec=True)
  def test_luci_auth_error(self, subprocess_mock):
    subprocess_mock.side_effect = subprocess.CalledProcessError(
        1, ['luci-auth', 'token', '-scopes', 'newscope'])

    with self.assertRaisesRegex(
        gmail.LuciAuthError,
        'The following scopes are required to send emails with the Gmail API: '
        r"\['https://www.googleapis.com/auth/gmail.send'\]. Please log in with "
        '`luci-auth login -scopes https://www.googleapis.com/auth/gmail.send`.'
    ):
      self._announcer.send_email()
