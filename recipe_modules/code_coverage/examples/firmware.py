# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'build_menu',
    'cros_build_api',
]

from recipe_engine import post_process


def RunSteps(api):
  with api.build_menu.configure_builder() as config, \
      api.build_menu.setup_workspace_and_chroot():
    # Build and test firmware.
    api.build_menu.upload_artifacts(config=config, failing_build=False)


def GenTests(api):

  yield api.build_menu.test(
      'basic',
      api.cros_build_api.set_api_return(
          'upload artifacts', 'FirmwareService/BundleFirmwareArtifacts',
          data=('{"artifacts": {"artifacts": [{"artifact_type":"FIRMWARE_LCOV",'
                '"paths": [{"path":"[START_DIR]/coverage.tbz2","location":2}],'
                '"location": "PLATFORM_EC"}]}}')), cq=True, builder='fw-ec-cq')
