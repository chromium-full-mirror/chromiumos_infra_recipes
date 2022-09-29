# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.chromiumos.builder_config import BuilderConfig

DEPS = [
    'recipe_engine/assertions',
    'cros_artifacts',
    'cros_test_plan',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  build_payload = api.cros_test_plan.test_api.test_unit_common(
      artifacts=[BuilderConfig.Artifacts.IMAGE_ZIP]).build_payload

  api.assertions.assertRaises(ValueError, api.cros_artifacts.download_artifacts,
                              build_payload,
                              [BuilderConfig.Artifacts.EBUILD_LOGS])


def GenTests(api):
  yield api.test('tests')
