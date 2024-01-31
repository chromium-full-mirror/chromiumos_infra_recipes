# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromite.api import sysroot

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'cros_build_api',
]



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
      api.post_check(post_process.PropertiesContain, 'caught_exceptions'),
  )
