# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import base64
import email.message
import subprocess
from typing import List, Optional
import urllib.parse

import google.oauth2.credentials
import googleapiclient.discovery
import tabulate

import common
import git


def _get_subject():
  """Return a subject for the announcement email."""
  return f'Recipes Release - {common.get_timestamp()}'


# Template for the body of the announcement email.
_MESSAGE_TEMPLATE = '''
We've deployed Recipes (for {bundle_longname}) to prod!

Here is a summary of the changes:

{change_table}
'''

_REQUIRED_SCOPES = ['https://www.googleapis.com/auth/gmail.send']


class GmailAnnouncer:
  """Builds emails to announce a recipes release.

  GmailAnnouncer formats the list of pending changes into a table, and produces
  a link to send the announcement email or sends the email directly.
  """

  def __init__(
      self,
      pending_changes: List[git.Commit],
      bundle_longname: str,
      recipients: List[str],
      bccs: List[str],
      quota_project: Optional[str] = None,
  ):
    """Initialize the GmailAnnouncer based on a set of pending changes.

    Args:
      pending_changes: Changes that will be released. Note that announcer does
        nothing to check whether the changes have been / will be released.
      bundle_longname: Human-readable name of the Recipes bundle being released.
      recipients: Email addresses to send the announcement to.
      bccs: Email addresses to bcc on the announcement.
      quota_project: Cloud quota project to used when sending emails through the
        Gmail API. Not needed if the announcer is just producing a link to send
        the email.
    """
    # Formatting the table should be fast, do it in __init__.
    change_table = tabulate.tabulate(
        [['*'] + c.plain_strs() for c in pending_changes if not c.trivial],
        headers=[], tablefmt='plain')
    self._message = _MESSAGE_TEMPLATE.format(bundle_longname=bundle_longname,
                                             change_table=change_table)
    self._recipients = recipients
    self._bccs = bccs
    self._quota_project = quota_project

  def get_email_link(self) -> str:
    """Get a link to send the announcement email.

    The link should be printed by a script so that the human running it can
    click it and send the email.
    """
    url_params = urllib.parse.urlencode({
        'view': 'cm',
        'fs': 1,
        'bcc': ','.join(self._bccs),
        'to': ','.join(self._recipients),
        'su': _get_subject(),
        'body': self._message,
    })
    return f'https://mail.google.com/mail?{url_params}'

  def send_email(self):
    """Send the announcement email through the Gmail API.

    Uses a token produced by `luci-auth token` to authenticate with the Gmail
    API. The caller must be logged in with `luci-auth` with the appropriate
    scopes.
    """
    service = googleapiclient.discovery.build(
        'gmail', 'v1', credentials=self._creds_from_luci())

    message = email.message.EmailMessage()
    message.set_content(self._message)
    message['To'] = self._recipients
    message['Bcc'] = self._bccs
    message['Subject'] = _get_subject()

    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

    create_message = {'raw': encoded_message}

    service.users().messages().send(userId="me", body=create_message).execute()

  def _creds_from_luci(self) -> google.oauth2.credentials.Credentials:
    """Call `luci-auth token` to build Credentials.

    Note that this will fail if the caller is not logged in with the required
    scopes.
    """
    if not self._quota_project:
      raise ValueError('quota_project must be set')

    # TODO(b/287276108): Produce a clear error message when not logged in.
    token_proc = subprocess.run(
        ['luci-auth', 'token', '-scopes', ' '.join(_REQUIRED_SCOPES)],
        check=True, stdout=subprocess.PIPE)
    token = token_proc.stdout
    return google.oauth2.credentials.Credentials(token).with_quota_project(
        self._quota_project)
