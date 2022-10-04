# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.chromite.api.sysroot import Sysroot
from PB.chromiumos.common import BuildTarget, Profile
from PB.chromiumos.builder_config import BuilderConfig
from PB.recipe_modules.chromeos.cros_prebuilts.cros_prebuilts import CrosPrebuiltsProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_prebuilts',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  # Uploading prebuilts for a CQ builder is invalid and raises ValueError.
  # _binhost_key() is where we discover that we do not have a key for that
  # value.
  target = BuildTarget(name='target')
  api.assertions.assertRaises(ValueError,
                              api.cros_prebuilts.upload_target_prebuilts,
                              target, Sysroot(build_target=target),
                              Profile(name='profile_name'), BuilderConfig.Id.CQ,
                              'prebuilts_gs_bucket')


def GenTests(api):
  yield api.test('basic')

  yield api.test(
      'staging-branch',
      api.properties(
          **{
              "$chromeos/cros_prebuilts":
                  CrosPrebuiltsProperties(use_staging_branch=True)
          }),
  )
