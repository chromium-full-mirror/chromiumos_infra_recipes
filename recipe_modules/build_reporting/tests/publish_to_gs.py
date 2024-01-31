# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'build_reporting',
]



def RunSteps(api):
  with api.step.nest('both fail'):

    def both_fail():
      with api.build_reporting.publish_to_gs():
        raise ValueError('bad value')

    api.assertions.assertRaises(ValueError, both_fail)

  with api.step.nest('inner fail'):

    def inner_fail():
      with api.build_reporting.publish_to_gs():
        raise ValueError('bad value')

    api.assertions.assertRaises(ValueError, inner_fail)

  with api.step.nest('outer fail'):

    def outer_fail():
      with api.build_reporting.publish_to_gs():
        pass

    api.assertions.assertRaises(StepFailure, outer_fail)


def GenTests(api):
  yield api.test(
      'basic',
      api.step_data(
          'both fail.upload build report to GS.write buildreport json to tmp file',
          retcode=1),
      api.step_data(
          'outer fail.upload build report to GS.write buildreport json to tmp file',
          retcode=1),
      api.post_process(post_process.DropExpectation),
  )
