# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process

DEPS = [
    'recipe_engine/properties',
    'manifest_doctor',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  api.manifest_doctor([
      'public-buildspec',
      '--paths',
      'buildspecs/',
      '--push',
  ], step_name='run manifest_doctor')


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          **{
              '$chromeos/manifest_doctor': {
                  'manifest_doctor_cipd_package':
                      'chromiumos/infra/manifest_doctor_foo',
                  'manifest_doctor_cipd_ref':
                      'bar'
              }
          }),
      api.post_check(post_process.StepCommandContains,
                     'ensure manifest_doctor.ensure_installed',
                     ['chromiumos/infra/manifest_doctor_foo bar']),
      api.post_check(post_process.StepCommandContains, 'run manifest_doctor',
                     ['public-buildspec', '--paths', 'buildspecs/', '--push']),
      api.post_process(post_process.DropExpectation))
