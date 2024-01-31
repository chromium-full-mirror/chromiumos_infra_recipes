# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

DEPS = [
    'recipe_engine/assertions',
    'cros_infra_config',
]



def RunSteps(api):
  policies = api.cros_infra_config.get_dut_tracking_config().policies
  api.assertions.assertEqual(len(policies), 1)
  api.assertions.assertEqual(policies[0].name, 'atlas')


def GenTests(api):
  yield api.test('basic')
