# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/path',
    'recipe_engine/properties',
    'cros_prebuilts',
]

from PB.chromiumos import common


def RunSteps(api):
  target = common.BuildTarget()
  target.name = 'target'
  api.cros_prebuilts.upload_target_prebuilts(target, 'postsubmit')


def GenTests(api):
  yield api.test('basic')

  yield (api.test('staging_branch') +  #
         api.properties(prebuilts_use_staging_branch=True))
