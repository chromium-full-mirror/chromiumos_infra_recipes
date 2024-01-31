# -*- coding: utf-8 -*-

# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

DEPS = [
    'recipe_engine/assertions',
    'metadata',
]



def RunSteps(api):
  gs_bucket = 'chromeos-image-archive'
  gs_path = 'target-cq/R12-3.4.5-6789'
  metadata_rel_path = 'metadata/containers.jsonpb'
  # Check relative path
  api.assertions.assertEqual(
      api.metadata.gspath(
          api.metadata.METADATA_PAYLOADS['container'],
      ),
      metadata_rel_path,
  )

  # Check full path
  api.assertions.assertEqual(
      api.metadata.gspath(api.metadata.METADATA_PAYLOADS['container'],
                          gs_bucket, gs_path),
      'gs://{}/{}/{}'.format(gs_bucket, gs_path, metadata_rel_path),
  )

  # Force coverage on mock metadata
  _ = api.metadata.test_api.mock_metadata()


def GenTests(api):
  yield api.test('basic')
