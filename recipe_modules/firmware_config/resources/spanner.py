# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Minimal Cloud Spanner REST client for recipe resource scripts."""

from collections.abc import Sequence
from typing import Any

import requests
from requests import adapters
from urllib3.util import retry

API = 'https://spanner.googleapis.com/v1'
COMMIT_TIMESTAMP = 'spanner.commit_timestamp()'

# A row costs one mutation per column plus one per index, and Spanner accepts
# at most 80k mutations in a commit.
MAX_ROWS_PER_COMMIT = 5000
ATTEMPTS = 5
# 409 is Spanner's ABORTED, which is meant to be retried.
RETRY_CODES = (409, 429, 500, 502, 503, 504)


def int64(value: int | None) -> str | None:
  """Returns value as the string that the REST API takes for an INT64."""
  return None if value is None else str(value)


def upsert(table: str, columns: Sequence[str],
           rows: Sequence[Sequence[Any]]) -> dict[str, Any]:
  """Returns an insertOrUpdate mutation dict for table."""
  return {
      'insertOrUpdate': {
          'table': table,
          'columns': list(columns),
          'values': [list(row) for row in rows],
      }
  }


class Database:
  """A Cloud Spanner database handle backed by the v1 REST API."""

  def __init__(self, project: str, instance: str, database: str,
               token: str) -> None:
    self.project = project
    self.name = f'projects/{project}/instances/{instance}/databases/{database}'
    self.token = token
    self._session: str | None = None
    self._http = requests.Session()
    self._http.headers.update({
        'Authorization': f'Bearer {token}',
        # The builders live in another project, so bill the API to ours.
        'X-Goog-User-Project': project,
    })
    retries = retry.Retry(
        total=ATTEMPTS - 1,
        backoff_factor=1,
        status_forcelist=RETRY_CODES,
        allowed_methods=['POST'],
    )
    self._http.mount('https://', adapters.HTTPAdapter(max_retries=retries))

  def request(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
    """POSTs body to the Spanner REST API, retrying transient errors."""
    response = self._http.post(f'{API}/{path}', json=body, timeout=60)
    if not response.ok:
      raise RuntimeError(
          f'{path}: HTTP {response.status_code}: {response.text}')
    return response.json() if response.content else {}

  def session(self) -> str:
    """Returns a session name, creating one on first use.

    Sessions are never deleted: Spanner collects them after an idle hour and a
    build only opens one.
    """
    if self._session is None:
      self._session = self.request(f'{self.name}/sessions', {})['name']
    return self._session

  def read_keys(self, table: str, column: str, keys: Sequence[str]) -> set[str]:
    """Returns the subset of single-column keys that already exist in table."""
    if not keys:
      return set()
    rows = self.request(
        f'{self.session()}:read',
        {
            'table': table,
            'columns': [column],
            'keySet': {
                'keys': [[key] for key in keys]
            },
        },
    ).get('rows', [])
    return {row[0] for row in rows}

  def commit(self, *mutations: dict[str, Any]) -> None:
    """Commits mutations in a single-use read-write transaction."""
    self.request(
        f'{self.session()}:commit',
        {
            'singleUseTransaction': {
                'readWrite': {}
            },
            'mutations': list(mutations),
        },
    )

  def commit_rows(self, table: str, columns: Sequence[str],
                  rows: Sequence[Sequence[Any]]) -> None:
    """Commits rows to table in chunks of MAX_ROWS_PER_COMMIT."""
    for i in range(0, len(rows), MAX_ROWS_PER_COMMIT):
      self.commit(upsert(table, columns, rows[i:i + MAX_ROWS_PER_COMMIT]))
