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
  all_policies = api.cros_infra_config.get_bot_policy_config().bot_policies
  api.assertions.assertEqual(len(all_policies), 1)
  api.assertions.assertEqual(all_policies[0].bot_group, 'cq')


def GenTests(api):
  yield api.test('basic')
