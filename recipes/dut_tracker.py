# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the Star Doctor.

Automatically updates binary config files and updates Goldeneye config
json files.
"""

DEPS = [
    'recipe_engine/step',
    'cros_infra_config',
]


def RunSteps(api):
  with api.step.nest('get config'):
    tracking_policies = (
        api.cros_infra_config.get_dut_tracking_config().policies)

  # with api.step.nest('query swarming'):
  #   for policy in tracking_policies:
  #     pass


def GenTests(api):
  yield api.test('basic')
