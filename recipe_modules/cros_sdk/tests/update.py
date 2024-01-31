# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf import json_format

from PB.chromite.api import sdk

from recipe_engine import post_process

DEPS = [
    'cros_build_api',
    'cros_sdk',
]



def RunSteps(api):
  api.cros_sdk.update_chroot()


def GenTests(api):

  yield api.test(
      'basic',
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'without_use_flags',
      api.cros_build_api.set_api_return('update sdk',
                                        endpoint='SdkService/Update', data='{}',
                                        retcode=0),
  )

  yield api.test(
      'non-pkg-failure',
      api.cros_build_api.set_api_return('update sdk',
                                        endpoint='SdkService/Update', data='{}',
                                        retcode=1),
      api.post_process(
          post_process.SummaryMarkdown,
          "Step('update sdk.call chromite.api.SdkService/Update.call build API script') (retcode: 1)"
      ),
      api.post_process(post_process.MustRun, 'update sdk.UpdateSDK failure'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  data = sdk.UpdateResponse()
  pkg = data.failed_package_data.add()
  pkg.name.package_name = 'bar'
  pkg.name.category = 'foo'
  pkg.name.version = '1.0-r1'
  pkg.log_path.path = '/path/to/foog:bar-1.0-r1'
  yield api.test(
      'pkg-failure',
      api.cros_build_api.set_api_return('update sdk',
                                        endpoint='SdkService/Update',
                                        data=json_format.MessageToJson(data),
                                        retcode=2),
      api.post_process(
          post_process.SummaryMarkdown,
          'failed compilation for [foo/bar-1.0-r1](https:///logs///+/u/update_sdk/foo_bar_log)'
      ),
      api.post_process(post_process.MustRun, 'update sdk.UpdateSDK failure'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )
