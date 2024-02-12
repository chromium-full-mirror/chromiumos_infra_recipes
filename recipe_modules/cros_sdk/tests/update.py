# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf import json_format

from PB.chromite.api import depgraph
from PB.chromite.api import sdk
from PB.chromite.api import sysroot
from PB.chromiumos import common
from PB.recipe_modules.chromeos.failures.failures import PackageFailure

from recipe_engine import post_process

DEPS = [
    'recipe_engine/buildbucket',
    'cros_build_api',
    'cros_sdk',
    'workspace_util',
]



def RunSteps(api):
  # Changes need to be applied for failure attribution.
  api.workspace_util.apply_changes()
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

  pkg_info = common.PackageInfo(category='foo', package_name='bar',
                                version='1.0-r1')
  data = sdk.UpdateResponse(failed_package_data=[
      sysroot.FailedPackageData(
          name=pkg_info, log_path=common.Path(path='/path/to/foog:bar-1.0-r1'))
  ])
  yield api.test(
      'pkg-failure',
      api.buildbucket.try_build(),
      api.cros_build_api.set_api_return('update sdk',
                                        endpoint='SdkService/Update',
                                        data=json_format.MessageToJson(data),
                                        retcode=2),
      api.post_process(
          post_process.SummaryMarkdown,
          'failed compilation for [foo/bar-1.0-r1](https:///logs///+/u/update_sdk/foo_bar_log)'
      ),
      api.post_process(post_process.PropertyEquals, 'package_failures', [
          json_format.MessageToDict(
              PackageFailure(package=pkg_info, phase='COMPILE',
                             affected_by_changes=False))
      ]),
      api.post_process(post_process.MustRun, 'update sdk.UpdateSDK failure'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'pkg-failure-with-attribution',
      api.buildbucket.try_build(),
      api.cros_build_api.set_api_return('update sdk',
                                        endpoint='SdkService/Update',
                                        data=json_format.MessageToJson(data),
                                        retcode=2),
      api.cros_build_api.set_api_return(
          'update sdk.get package dependencies', 'DependencyService/List',
          json_format.MessageToJson(
              depgraph.ListResponse(package_deps=[pkg_info]))),
      api.post_process(
          post_process.SummaryMarkdown,
          'failed compilation for [foo/bar-1.0-r1](https:///logs///+/u/update_sdk/foo_bar_log)'
      ),
      api.post_process(post_process.PropertyEquals, 'package_failures', [
          json_format.MessageToDict(
              PackageFailure(package=pkg_info, phase='COMPILE',
                             affected_by_changes=True))
      ]),
      api.post_process(post_process.MustRun, 'update sdk.UpdateSDK failure'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )
