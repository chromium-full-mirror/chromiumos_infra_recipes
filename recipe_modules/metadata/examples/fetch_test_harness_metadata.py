# -*- coding: utf-8 -*-

# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test generator for fetch_test_harness_metadata function."""

from typing import Generator

from PB.chromite.api.sysroot import Sysroot
from PB.chromiumos.common import Chroot
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_build_api',
    'metadata',
]


def RunSteps(api: RecipeApi) -> None:
  output = api.metadata.fetch_test_harness_metadata(
      chroot=Chroot(), sysroot=Sysroot(),
      mock_metadata_file=api.properties['file_exists'])

  example_metadata = api.metadata.EXAMPLE_TEST_HARNESS_METADATA_LIST
  if api.properties['valid_return']:
    api.assertions.assertEqual(output, example_metadata)
  else:
    api.assertions.assertIsNone(output)


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  yield api.test('fetch-test-harness-metadata-valid',
                 api.properties(valid_return=True, file_exists=True))
  yield api.test(
      'fetch-test-harness-metadata-no-endpoint',
      api.cros_build_api.remove_endpoints(
          ['ArtifactsService/FetchTestHarnessMetadata']),
      api.properties(valid_return=False, file_exists=True),
  )
  yield api.test(
      'fetch-test-harness-metadata-bad-file',
      api.properties(valid_return=False, file_exists=False),
  )
