# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'cros_sdk',
]

from PB.chromiumos import common
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.cros_sdk.examples.test import (
    TestInputProperties)

PROPERTIES = TestInputProperties


def RunSteps(api, properties):
  workspace = api.path['cleanup'].join('workspace')

  with api.cros_sdk.cleanup_context(checkout_path=workspace):
    api.cros_sdk.configure(chroot_parent_path=api.path['cleanup'].join('test'))
    api.assertions.assertTrue(
        api.cros_sdk.chroot.path.endswith('test/cros_chroot'))

    api.assertions.assertIsNone(api.cros_sdk.goma_config())

    chroot = api.cros_sdk.create_chroot(version=properties.sdk_version)
    api.assertions.assertNotEqual(chroot, None)
    api.cros_sdk.update_chroot(properties.gitiles_commit,
                               properties.gerrit_changes)

    api.cros_sdk.uprev_packages()

    api.cros_sdk.set_chrome_root('/chrome_dir')
    api.cros_sdk.set_goma_config('/goma_dir', '/creds/goma.json',
                                 common.GomaConfig.RBE_PROD, '/goma_logs',
                                 'stats.file', 'counterz.file')
    api.cros_sdk.set_use_flags([common.UseFlag(flag='goma')])
    chroot = api.cros_sdk.chroot
    with api.cros_sdk.snapshot():
      api.assertions.assertEqual(chroot.chrome_dir, '/chrome_dir')
      api.assertions.assertTrue(api.cros_sdk.has_goma_config())
      api.assertions.assertItemsEqual(chroot.env.use_flags,
                                      [common.UseFlag(flag='goma')])

    goma = api.cros_sdk.goma_config()
    api.assertions.assertEqual(goma.goma_dir, '/goma_dir')
    api.assertions.assertEqual(goma.goma_client_json, '/creds/goma.json')
    api.assertions.assertEqual(goma.log_dir, common.SyncedDir(dir='/goma_logs'))
    api.assertions.assertEqual(goma.stats_file, 'stats.file')
    api.assertions.assertEqual(goma.counterz_file, 'counterz.file')

    api.cros_sdk('get cros_sdk help', ['--help'])
    api.cros_sdk.run('ls in chroot', ['ls'], env={'PATH': '/bin'},
                     workspace=workspace)

    api.cros_sdk.link_chroot(workspace)

    # Link a second time to handle case where link exists.
    api.cros_sdk.link_chroot(workspace)

    api.cros_sdk.unmount_chroot()

    api.cros_sdk.unlink_chroot(workspace)
    api.cros_sdk.swarming_chmod_chroot()


def GenTests(api):
  yield api.test('basic')

  yield (api.test('versioned') +  #
         api.properties(TestInputProperties(sdk_version=3)) +  #
         api.step_data('init sdk.read sdk cache version json',
                       api.raw_io.output_text('{"version": "1"}')))

  yield (api.test('with changes') +  #
         api.properties(TestInputProperties(
             gerrit_changes=[common_pb2.GerritChange(change=1234)])))

  yield (api.test('failed-step-init-sdk') +  #
         api.step_data(
             'init sdk.call chromite.api.SdkService/'
             'Create.call build API script', retcode=1))

  yield (api.test('failed-step-update-sdk') +  #
         api.step_data(
             'update sdk.call chromite.api.SdkService/'
             'Update.call build API script', retcode=1))

  yield (api.test('failed-step-destroy-chroot-tests') +  #
         api.step_data('link chroot in workspace.ensure workspace', retcode=1))

  yield (api.test('failed-restore-to-snapshot-test') +  #
         api.step_data(
             ('restoring chroot from snapshot.call chromite.api.SdkService/'
              'RestoreSnapshot.call build API script'), retcode=1))
