#!/usr/bin/env vpython3
# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# [VPYTHON:BEGIN]
# python_version: "3.11"
# wheel: <
#   name: "infra/python/wheels/requests-py3"
#   version: "version:2.31.0"
# >
# wheel: <
#   name: "infra/python/wheels/urllib3-py2_py3"
#   version: "version:1.26.6"
# >
# wheel: <
#   name: "infra/python/wheels/certifi-py2_py3"
#   version: "version:2021.5.30"
# >
# wheel: <
#   name: "infra/python/wheels/charset_normalizer-py3"
#   version: "version:2.0.4"
# >
# wheel: <
#   name: "infra/python/wheels/idna-py2_py3"
#   version: "version:2.10"
# >
# [VPYTHON:END]

"""Tests for spanner.py."""

import os
import sys
from typing import Any
import unittest
from unittest import mock

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import spanner  # pylint: disable=wrong-import-position


class SpannerTest(unittest.TestCase):
  """Unit tests for the Cloud Spanner REST client."""

  @staticmethod
  def make_response(code: int, body: bytes = b'boom') -> requests.Response:
    """Returns a requests.Response with status code and raw body."""
    response = requests.Response()
    response.status_code = code
    response.encoding = 'utf-8'
    response._content = body  # pylint: disable=protected-access
    return response

  def test_int64_and_upsert(self) -> None:
    self.assertIsNone(spanner.int64(None))
    self.assertEqual(spanner.int64(42), '42')
    self.assertEqual(
        spanner.upsert('T', ('A', 'B'), [(1, 2)]),
        {
            'insertOrUpdate': {
                'table': 'T',
                'columns': ['A', 'B'],
                'values': [[1, 2]],
            }
        },
    )

  def test_session_read_keys_and_commit_rows(self) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_request(path: str, body: dict[str, Any]) -> dict[str, Any]:
      calls.append((path, body))
      if path.endswith('/sessions'):
        return {'name': 'projects/p/instances/i/databases/d/sessions/s'}
      if path.endswith(':read'):
        return {'rows': [['k1']]}
      return {}

    db = spanner.Database('p', 'i', 'd', 'tok')
    with mock.patch.object(db, 'request', side_effect=fake_request):
      self.assertEqual(db.read_keys('T', 'K', []), set())
      self.assertEqual(db.read_keys('T', 'K', ['k1', 'k2']), {'k1'})
      with mock.patch.object(spanner, 'MAX_ROWS_PER_COMMIT', 2):
        db.commit_rows('T', ['K'], [['a'], ['b'], ['c']])

    # Session is created once and reused across read and commits.
    self.assertEqual(
        [path for path, _ in calls],
        [
            'projects/p/instances/i/databases/d/sessions',
            'projects/p/instances/i/databases/d/sessions/s:read',
            'projects/p/instances/i/databases/d/sessions/s:commit',
            'projects/p/instances/i/databases/d/sessions/s:commit',
        ],
    )

  def test_request_posts_json_and_handles_empty_body(self) -> None:
    db = spanner.Database('p', 'i', 'd', 'tok')
    with mock.patch.object(
        requests.Session,
        'post',
        side_effect=[
            self.make_response(200, b'{"a": 1}'),
            self.make_response(200, b''),
        ],
    ) as post:
      self.assertEqual(db.request('path', {'k': 'v'}), {'a': 1})
      self.assertEqual(db.request('path', {}), {})
    post.assert_any_call(f'{spanner.API}/path', json={'k': 'v'}, timeout=60)

  def test_error_raises_runtime_error_with_body(self) -> None:
    db = spanner.Database('p', 'i', 'd', 'tok')
    with mock.patch.object(requests.Session, 'post',
                           return_value=self.make_response(403)):
      with self.assertRaisesRegex(RuntimeError, '403.*boom'):
        db.request('path', {})


if __name__ == '__main__':
  unittest.main()
