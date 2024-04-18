# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromite.api.sysroot import Sysroot
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import Chroot
from PB.chromiumos.common import Profile
from PB.recipe_modules.chromeos.cros_prebuilts.cros_prebuilts import CrosPrebuiltsProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_prebuilts',
    'build_menu',
]

GERRIT_HOST = 'gerrit.host.test'
CHANGE_NUM = 12345



def RunSteps(api):
  # Uploading prebuilts for a CQ builder is invalid and raises ValueError.
  # _binhost_key() is where we discover that we do not have a key for that
  # value.
  target = BuildTarget(name='target')

  with api.build_menu.configure_builder():
    api.cros_prebuilts.upload_target_prebuilts(
        target,
        Sysroot(build_target=target),
        Chroot(path='/path/to/chroot', out_path='/path/to/out'),
        Profile(),
        BuilderConfig.Id.CQ,
        'prebuilts_gs_bucket',
    )


def GenTests(api):
  yield api.build_menu.test('basic')

  yield api.build_menu.test(
      'staging-branch',
      api.properties(
          **{
              '$chromeos/cros_prebuilts':
                  CrosPrebuiltsProperties(use_staging_branch=True)
          }),
      cq=True,
  )

  yield api.build_menu.test(
      'creating-prebuilt',
      api.properties(
          **{
              '$chromeos/cros_prebuilts':
                  CrosPrebuiltsProperties(send_snapshot_prebuilts=True,
                                          commit_overlay_binhost=False)
          }),
      cq=True,
  )

  yield api.build_menu.test(
      'staging-branch-creating-prebuilt',
      api.properties(
          **{
              '$chromeos/cros_prebuilts':
                  CrosPrebuiltsProperties(use_staging_branch=True,
                                          send_snapshot_prebuilts=True,
                                          commit_overlay_binhost=False)
          }),
      cq=True,
  )

  # Ensure CQ doesn't support committing prebuilts.
  yield api.build_menu.test(
      'creating-and-commiting-prebuilt',
      api.properties(
          **{
              '$chromeos/cros_prebuilts':
                  CrosPrebuiltsProperties(send_snapshot_prebuilts=True,
                                          commit_overlay_binhost=True)
          }),
      api.expect_exception('ValueError'),
      cq=True,
      status='INFRA_FAILURE',
  )

  # Ensure CQ doesn't support committing prebuilts (on staging branch).
  yield api.build_menu.test(
      'staging-branch-creating-and-commiting-prebuilt',
      api.properties(
          **{
              '$chromeos/cros_prebuilts':
                  CrosPrebuiltsProperties(use_staging_branch=True,
                                          send_snapshot_prebuilts=True,
                                          commit_overlay_binhost=True)
          }), api.expect_exception('ValueError'), cq=True,
      status='INFRA_FAILURE')
