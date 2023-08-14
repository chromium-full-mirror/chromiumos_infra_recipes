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


# Template for the body of the announcement email.
_MESSAGE_TEMPLATE = '''
We've deployed Recipes (for {bundle_longname}) to prod!
{bbid_message}
Here is a summary of the changes:

{change_table}
'''

REQUIRED_SCOPES = ['https://www.googleapis.com/auth/gmail.send']


class LuciAuthError(Exception):
  """Raised when luci-auth isn't logged in with required scopes."""


def get_token_from_luci_auth() -> bytes:
  """Call luci-auth to get a token with the required scopes.

  This function is used internally by the GmailAnnouncer class, and is also made
  public so callers can check early whether the user is logged in with the
  required scopes.
  """
  try:
    return subprocess.run(
        ['luci-auth', 'token', '-scopes', ' '.join(REQUIRED_SCOPES)],
        check=True, stdout=subprocess.PIPE).stdout
  except subprocess.CalledProcessError as e:
    raise LuciAuthError(
        'The following scopes are required to send emails with the Gmail API: '
        f'{REQUIRED_SCOPES}. Please log in with `luci-auth login -scopes '
        f'{" ".join(REQUIRED_SCOPES)}`.') from e


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
      dry_run: bool = False,
      quota_project: Optional[str] = None,
      bbid: Optional[str] = None,
  ):
    """Initialize the GmailAnnouncer based on a set of pending changes.

    Args:
      pending_changes: Changes that will be released. Note that announcer does
        nothing to check whether the changes have been / will be released.
        Changes will be appear in the announcement in the order they appear in
        this list, newest to oldest is the suggested order, so it matches the
        output of `git log`.
      bundle_longname: Human-readable name of the Recipes bundle being released.
      recipients: Email addresses to send the announcement to.
      bccs: Email addresses to bcc on the announcement.
      dry_run: Whether the changes are actually being released, affects the
        subject of the email. Similar to pending_changes, announcer does nothing
        to check whether the changes are actually being released.
      quota_project: Cloud quota project to used when sending emails through the
        Gmail API. Not needed if the announcer is just producing a link to send
        the email.
      bbid: BBID of the invoking builder, which will be included in the
        announcement email. Not for use by humans.
    """
    # Formatting the table should be fast, do it in __init__.
    change_table = tabulate.tabulate(
        [['*'] + c.plain_strs() for c in pending_changes if not c.trivial],
        headers=[], tablefmt='plain')
    bbid_message = f'\nRecipes deployed by go/bbid/{bbid}.\n' if bbid else ''
    self._body = _MESSAGE_TEMPLATE.format(bundle_longname=bundle_longname,
                                          bbid_message=bbid_message,
                                          change_table=change_table)
    self._recipients = recipients
    self._dry_run = dry_run
    self._bccs = bccs
    self._quota_project = quota_project

  def get_subject(self):
    """Return a subject for the announcement email."""
    return f'{"[DRY RUN] " if self._dry_run else ""}Recipes Release - {common.get_timestamp()}'

  @property
  def body(self):
    return self._body

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
        'su': self.get_subject(),
        'body': self._body,
    })
    return f'https://mail.google.com/mail?{url_params}'

  def send_email(self):
    """Send the announcement email through the Gmail API.

    Uses a token produced by `luci-auth token` to authenticate with the Gmail
    API. The caller must be logged in with `luci-auth` with the appropriate
    scopes.
    """
    if not self._quota_project:
      raise ValueError('quota_project must be set')

    creds = google.oauth2.credentials.Credentials(
        get_token_from_luci_auth()).with_quota_project(self._quota_project)

    service = googleapiclient.discovery.build('gmail', 'v1', credentials=creds)

    message = email.message.EmailMessage()
    message.set_content(self._body)
    message['To'] = self._recipients
    message['Bcc'] = self._bccs
    message['Subject'] = self.get_subject()

    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

    create_message = {'raw': encoded_message}

    service.users().messages().send(userId="me", body=create_message).execute()
