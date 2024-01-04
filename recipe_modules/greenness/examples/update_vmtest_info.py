# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'greenness',
    'test_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  builds = [
      api.test_util.test_api.test_child_build(
          build_target_name='betty', output_properties={
              'greenness': '78'
          }, input_properties={
              'name': 'betty-arc-r-cq.tast_vm.direct_tast_vm_shard_3_of_5'
          }).message
  ]
  api.greenness.update_vmtest_info(builds)
  api.assertions.assertEqual(api.greenness.greenness_dict['betty'].score, 78)
  api.greenness.print_step()


def GenTests(api):
  yield api.test('basic')
