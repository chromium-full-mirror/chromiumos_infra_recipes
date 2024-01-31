# -*- coding: utf-8 -*-

# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

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
  output = api.metadata.fetch_test_metadata(
      chroot=Chroot(), sysroot=Sysroot(),
      mock_metadata_file=api.properties['file_exists'])

  if api.properties['valid_return']:
    api.assertions.assertEqual(output, api.metadata.EXAMPLE_TEST_METADATA_LIST)
  else:
    api.assertions.assertIsNone(output)


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  yield api.test('fetch-test-metadata-valid',
                 api.properties(valid_return=True, file_exists=True))
  yield api.test(
      'fetch-test-metadata-no-endpoint',
      api.cros_build_api.remove_endpoints(['ArtifactsService/FetchMetadata']),
      api.properties(valid_return=False, file_exists=True),
  )
  yield api.test(
      'fetch-test-metadata-bad-file',
      api.properties(valid_return=False, file_exists=False),
  )
