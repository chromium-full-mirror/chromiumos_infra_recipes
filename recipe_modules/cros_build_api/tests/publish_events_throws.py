# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.chromite.api import sysroot

DEPS = [
    'recipe_engine/assertions',
    'cros_build_api',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  # InstallPackagesRequest can be published.
  input_proto = sysroot.InstallPackagesRequest(packages=[{
      'package_name': 'a_test_package'
  }])
  # This should not throw.
  output_proto = api.cros_build_api.SysrootService.InstallPackages(
      input_proto, name='install packages step')
  api.assertions.assertEqual(len(output_proto.failed_package_data), 0)


def GenTests(api):

  def StepMetaEquals(check, step_odict, step, expected):
    """Check that the step's step text equals given value.

    Assumes order does not matter.

    Args:
      step (str) - The step to check the step text of.
      expected (str) - The expected value of the step text.

    Usage:
      yield TEST + \
          api.post_process(StepSummaryEquals, 'step-name', 'expected-text')
    """
    check(step_odict[step].step_text == expected)

  yield api.test(
      'basic',
      api.step_data(
          'install packages step.publish event.publish message.publish-message',
          retcode=1),
      api.step_data(
          'install packages step.publish event.publish message (2).publish-message',
          retcode=1),
      api.step_data(
          'install packages step.publish event.publish message (3).publish-message',
          retcode=1),
      api.post_check(StepMetaEquals, 'install packages step',
                     'failed to publish pubsub message to analysis service'),
  )
