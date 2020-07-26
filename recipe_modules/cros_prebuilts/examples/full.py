# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'recipe_engine/properties',
    'cros_prebuilts',
]

from PB.chromiumos.common import BuildTarget
from PB.chromiumos.builder_config import BuilderConfig
from PB.recipe_modules.chromeos.cros_prebuilts.cros_prebuilts import (
    CrosPrebuiltsProperties)


def RunSteps(api):
  target = BuildTarget(name='target')
  api.cros_prebuilts.upload_target_prebuilts(target,
                                             BuilderConfig.Id.POSTSUBMIT,
                                             'prebuilts_gs_bucket')
  api.cros_prebuilts.upload_target_prebuilts(target,
                                             BuilderConfig.Id.POSTSUBMIT,
                                             'prebuilts_gs_bucket', False)
  api.assertions.assertRaises(ValueError,
                              api.cros_prebuilts.upload_target_prebuilts,
                              target, BuilderConfig.Id.CQ,
                              'prebuilts_gs_bucket')


def GenTests(api):
  yield api.test('basic')

  yield api.test(
      'staging_branch',
      api.properties(
          **{
              "$chromeos/cros_prebuilts":
                  CrosPrebuiltsProperties(use_staging_branch=True)
          }),
  )
