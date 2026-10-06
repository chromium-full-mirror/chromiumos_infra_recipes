# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

DEPS = [
    'recipe_engine/swarming',
    'build_menu',
    'cros_build_api',
]



def RunSteps(api):
  with api.build_menu.configure_builder() as config, \
      api.build_menu.setup_workspace_and_chroot():
    api.build_menu.upload_artifacts(config=config, upload_coverage=True)


def GenTests(api):

  yield api.build_menu.test(
      'basic',
      api.cros_build_api.set_api_return(
          'upload artifacts', 'FirmwareService/BundleFirmwareArtifacts', data=(
              '{"artifacts": {"artifacts": [{"artifact_type":"FIRMWARE_LCOV",'
              '"paths": [{"path":"[CLEANUP]/artifacts_tmp_1/coverage.tbz2","location":2}],'
              '"location": "PLATFORM_EC"}]}}')),
      api.post_check(
          post_process.MustRun,
          'upload artifacts.upload code coverage data (firmware lcov)'),
      cq=True, builder='fw-ec-cq')
