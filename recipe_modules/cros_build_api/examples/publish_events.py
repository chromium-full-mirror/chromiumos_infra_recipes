# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'cros_build_api',
]

from PB.chromite.api import sysroot


def RunSteps(api):
  # InstallPackagesRequest can be published.
  input_proto = sysroot.InstallPackagesRequest(packages=[{
      'package_name': 'a_test_package'
  }])
  output_proto = api.cros_build_api.SysrootService.InstallPackages(input_proto)
  api.assertions.assertEqual(len(output_proto.failed_packages), 0)


def GenTests(api):
  yield api.test('basic')

  # Have the actual publish-message binary return 1, to generate an exception.
  yield (api.test('publish-message-bad') +  #
         api.step_data(
             'call chromite.api.SysrootService/InstallPackages'
             '.publish event.publish message.publish-message', retcode=1))
