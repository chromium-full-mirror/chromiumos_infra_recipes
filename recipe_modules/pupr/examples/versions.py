# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for PUpr version serialization and metadata extraction."""

from PB.chromite.api import packages as packages_pb2
from recipe_engine import recipe_api
from RECIPE_MODULES.chromeos.pupr.api import deserialize_versions
from RECIPE_MODULES.chromeos.pupr.api import UPREV_VERSION_LABEL

DEPS = [
    'recipe_engine/assertions',
    'pupr',
]


def RunSteps(api):
  git_refs = [
      packages_pb2.UprevVersionedPackageRequest.GitRef(
          repository='repo1',
          ref='refs/tags/v1.0.0',
          revision='abc123',
      )
  ]
  serialized = (
      '[{"ref": "refs/tags/v1.0.0", "repository": "repo1", "revision":'
      ' "abc123"}]')
  deserialized = deserialize_versions(serialized)
  api.assertions.assertEqual(deserialized, git_refs)

  msg = f'Header\n\nChange-Id: I12345\n{UPREV_VERSION_LABEL}: {serialized}'

  # Test extract_upstream_git_refs with valid message.
  api.assertions.assertEqual(api.pupr.extract_upstream_git_refs(msg), git_refs)

  # Test extract_upstream_git_refs without footer.
  api.assertions.assertIsNone(
      api.pupr.extract_upstream_git_refs('No footer here'))

  # Test extract_upstream_git_refs with multiple footers.
  multi_msg = f'{msg}\n{UPREV_VERSION_LABEL}: {serialized}'
  try:
    api.pupr.extract_upstream_git_refs(multi_msg)
  except recipe_api.StepFailure:
    pass


def GenTests(api):
  yield api.test('basic')
