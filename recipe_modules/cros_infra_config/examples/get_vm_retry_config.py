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
  all_scenarios = api.cros_infra_config.get_vm_retry_config().suite_scenarios
  api.assertions.assertEqual(len(all_scenarios), 2)
  api.assertions.assertEqual(all_scenarios[0].test_name, 'arc.Boot')


def GenTests(api):
  yield api.test('basic')
