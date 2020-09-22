# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'cros_sdk',
    'goma',
    'workspace_util',
]

from PB.chromiumos import common
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.cros_sdk.examples.test import (
    TestInputProperties)
from PB.testplans.pointless_build import PointlessBuildCheckResponse

PROPERTIES = TestInputProperties


def RunSteps(api, properties):
  workspace = api.path['cleanup'].join('workspace')

  api.workspace_util.apply_changes(changes=properties.gerrit_changes or [])
  with api.cros_sdk.cleanup_context(checkout_path=workspace):
    api.cros_sdk.configure(chroot_parent_path=api.path['cleanup'].join('test'))
    api.assertions.assertTrue(
        api.cros_sdk.chroot.path.endswith('test/cros_chroot'))

    api.assertions.assertIsNone(api.cros_sdk.goma_config())

    chroot = api.cros_sdk.create_chroot(version=properties.sdk_cache_version)
    api.assertions.assertNotEqual(chroot, None)
    api.cros_sdk.update_chroot(properties.gitiles_commit,
                               properties.gerrit_changes)

    api.cros_sdk.uprev_packages()

    api.assertions.assertEqual(api.cros_sdk.long_timeouts,
                               api.workspace_util.toolchain_cls_applied)
    api.cros_sdk.configure_goma('/chrome_dir')
    api.cros_sdk.set_use_flags([common.UseFlag(flag='goma')])
    chroot = api.cros_sdk.chroot
    with api.cros_sdk.snapshot():
      api.assertions.assertEqual(chroot.chrome_dir, '/chrome_dir')
      api.assertions.assertTrue(api.cros_sdk.has_goma_config())
      api.assertions.assertItemsEqual(chroot.env.use_flags,
                                      [common.UseFlag(flag='goma')])

    goma = api.cros_sdk.goma_config()
    api.assertions.assertEqual(goma.goma_dir, str(api.goma.goma_dir))
    api.assertions.assertEqual(goma.goma_client_json,
                               str(api.goma.goma_client_json))
    api.assertions.assertEqual(goma.stats_file, 'stats.binaryproto')
    api.assertions.assertEqual(goma.counterz_file, 'counterz.binaryproto')

    api.cros_sdk('get cros_sdk help', ['--help'])
    api.cros_sdk.run('ls in chroot', ['ls'], env={'PATH': '/bin'})

    api.cros_sdk.link_chroot(workspace)

    # Link a second time to handle case where link exists.
    api.cros_sdk.link_chroot(workspace)

    api.cros_sdk.unmount_chroot()

    api.cros_sdk.unlink_chroot(workspace)
    api.cros_sdk.swarming_chmod_chroot()


def GenTests(api):
  yield api.test('basic')

  yield api.test(
      'versioned',
      api.step_data('init sdk.read sdk cache version json',
                    api.raw_io.output_text('{"version": 1}')))

  yield api.test(
      'with-changes',
      api.properties(
          TestInputProperties(
              gerrit_changes=[common_pb2.GerritChange(change=1234)])))

  yield api.test(
      'with-toolchain-changes',
      api.step_data(
          'init sdk.detect toolchain change.path relevancy check.'
          'read output file',
          api.file.read_raw(
              content=PointlessBuildCheckResponse().SerializeToString())),
      api.properties(
          TestInputProperties(
              gerrit_changes=[common_pb2.GerritChange(change=1234)])))

  yield api.test(
      'with-toolchain-changes-and-force-no-toolchain-cls',
      api.step_data(
          'init sdk.detect toolchain change.path relevancy check.'
          'read output file',
          api.file.read_raw(
              content=PointlessBuildCheckResponse().SerializeToString())),
      api.properties(
          **{'$chromeos/cros_sdk': dict(force_off_toolchain_changed=True)}),
      api.properties(
          TestInputProperties(
              gerrit_changes=[common_pb2.GerritChange(change=1234)])))

  yield api.test(
      'failed-step-init-sdk',
      api.step_data(
          'init sdk.call chromite.api.SdkService/'
          'Create.call build API script', retcode=1))

  yield api.test(
      'failed-step-update-sdk',
      api.step_data(
          'update sdk.call chromite.api.SdkService/'
          'Update.call build API script', retcode=1))

  yield api.test(
      'failed-step-destroy-chroot-tests',
      api.step_data('link chroot in workspace.ensure workspace', retcode=1))

  yield api.test(
      'failed-restore-to-snapshot-test',
      api.step_data(
          ('restoring chroot from snapshot.call chromite.api.SdkService/'
           'RestoreSnapshot.call build API script'), retcode=1))
