# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'cros_artifacts',
]

from PB.chromiumos import common
from PB.chromiumos.builder_config import BuilderConfig
from PB.testplans.generate_test_plan import BuildPayload


def RunSteps(api):
  build_payload = BuildPayload(
      artifacts_gs_bucket='gs://bucket',
      artifacts_gs_path='path')
  image_zip = BuilderConfig.Artifacts.IMAGE_ZIP

  download_paths_by_artifact = api.cros_artifacts.download_artifacts(
      build_payload, [image_zip])
  image_zip_download_path = download_paths_by_artifact[image_zip]
  api.assertions.assertTrue(
      str(download_paths_by_artifact[image_zip]).endswith('image.zip'))

  api.assertions.assertRaises(
        ValueError, api.cros_artifacts.download_artifacts,
        build_payload, [BuilderConfig.Artifacts.EBUILD_LOGS])

def GenTests(api):
  yield api.test('basic')
