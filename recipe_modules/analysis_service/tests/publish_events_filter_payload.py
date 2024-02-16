# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf import json_format
from PB.chromite.api.sysroot import InstallPackagesRequest, Sysroot, InstallPackagesResponse, FailedPackageData
from PB.chromiumos.common import BuildTarget, Profile, PackageInfo, Path, RemoteexecArtifacts

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'analysis_service',
    'cros_build_api',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

def RunSteps(api):
  input_proto = InstallPackagesRequest(
      sysroot=Sysroot(
          path='/build/my_target', build_target=BuildTarget(
              name='my_target', profile=Profile())))
  test_data = InstallPackagesResponse(
      failed_package_data=[
          FailedPackageData(
              name=PackageInfo(package_name='package1', category='category',
                               version='r1'),
              log_path=Path(path='/some/path', location=0))
      ], remoteexec_artifacts=RemoteexecArtifacts(
          log_files=['log1', 'log2', 'log3']))
  resp_json = json_format.MessageToJson(test_data,
                                        preserving_proto_field_name=True)

  output_proto = api.cros_build_api.SysrootService.InstallPackages(
      input_proto=input_proto, test_output_data=resp_json)

  api.assertions.assertTrue(len(output_proto.failed_package_data) > 0)


def GenTests(api):
  yield api.test(
      'basic-iterable',
      api.analysis_service.optional_field_name(
          'chromite.api.InstallPackagesResponse.failed_package_data'),
      api.post_check(
          post_process.MustRun,
          'call chromite.api.SysrootService/InstallPackages.publish event'),
      api.post_check(
          post_process.LogDoesNotContain,
          'call chromite.api.SysrootService/InstallPackages.publish event',
          'published event', ['failedPackageData']))

  yield api.test(
      'disabled',
      api.properties(
          **{'$chromeos/analysis_service': {
              'disable_publish': True
          }}),
      api.post_check(
          post_process.DoesNotRun,
          'call chromite.api.SysrootService/InstallPackages.publish event'),
  )

  yield api.test(
      'basic',
      api.analysis_service.optional_field_name(
          'chromite.api.InstallPackagesResponse.remoteexec_artifacts'),
      api.post_check(
          post_process.MustRun,
          'call chromite.api.SysrootService/InstallPackages.publish event'),
      api.post_check(
          post_process.LogDoesNotContain,
          'call chromite.api.SysrootService/InstallPackages.publish event',
          'published event', ['logFiles']))
