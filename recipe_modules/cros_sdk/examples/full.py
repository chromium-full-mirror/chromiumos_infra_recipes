# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromiumos import common
from PB.chromiumos.sdk_cache_state import SdkCacheState
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.cros_sdk.examples.test import TestInputProperties
from PB.recipe_modules.chromeos.goma.goma import GomaProperties
from PB.recipe_modules.chromeos.remoteexec.remoteexec import RemoteexecProperties
from PB.testplans.pointless_build import PointlessBuildCheckResponse
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'cros_sdk',
    'cros_version',
    'goma',
    'remoteexec',
    'workspace_util',
]


PROPERTIES = TestInputProperties


def RunSteps(api, properties):
  workspace = api.path.cleanup_dir.join('workspace')

  api.assertions.assertFalse(api.cros_sdk.sdk_is_dirty)
  api.assertions.assertEqual(api.cros_sdk.chroot,
                             api.cros_sdk.test_api.chroot())

  api.workspace_util.apply_changes(changes=properties.gerrit_changes or [])
  with api.cros_sdk.cleanup_context(checkout_path=workspace):
    api.assertions.assertIsNone(api.cros_sdk.goma_config())
    api.assertions.assertIsNone(api.cros_sdk.remoteexec_config)
    api.assertions.assertFalse(api.cros_sdk.has_remoteexec_config())

    chroot = api.cros_sdk.create_chroot(version=properties.sdk_cache_version)
    api.assertions.assertNotEqual(chroot, None)
    api.cros_sdk.update_chroot()

    api.assertions.assertEqual(api.cros_sdk.long_timeouts,
                               api.workspace_util.toolchain_cls_applied)

    api.cros_sdk.set_chrome_root('/chrome_dir')
    if properties.check_remoteexec:
      api.cros_sdk.configure_remoteexec()
      api.cros_sdk.set_use_flags([common.UseFlag(flag='remoteexec')])
      remoteexec = api.cros_sdk.remoteexec_config
      api.assertions.assertEqual(remoteexec.reclient_dir,
                                 str(api.remoteexec.reclient_dir))
      api.assertions.assertEqual(remoteexec.reproxy_cfg_file,
                                 str(api.remoteexec.reproxy_cfg_file))
      api.assertions.assertTrue(api.cros_sdk.has_remoteexec_config())
    else:
      api.assertions.assertRaises(ValueError, api.cros_sdk.configure_remoteexec)
      api.cros_sdk.configure_goma()
      api.cros_sdk.set_use_flags([common.UseFlag(flag='goma')])
      chroot = api.cros_sdk.chroot
      api.assertions.assertEqual(chroot.chrome_dir, '/chrome_dir')
      api.assertions.assertTrue(api.cros_sdk.has_goma_config())
      api.assertions.assertCountEqual(chroot.env.use_flags,
                                      [common.UseFlag(flag='goma')])

      goma = api.cros_sdk.goma_config()
      api.assertions.assertEqual(goma.goma_dir, str(api.goma.goma_dir))
      api.assertions.assertEqual(goma.stats_file, 'stats.binaryproto')
      api.assertions.assertEqual(goma.counterz_file, 'counterz.binaryproto')

    api.cros_sdk('get cros_sdk help', ['--help'])
    api.cros_sdk.run('ls in chroot', ['ls'], env={'PATH': '/bin'})

    api.cros_sdk.link_chroot(workspace)

    # Link a second time to handle case where link exists.
    api.cros_sdk.link_chroot(workspace)

    api.cros_sdk.unlink_chroot(workspace)
    api.cros_sdk.swarming_chmod_chroot()


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          **{
              '$chromeos/goma':
                  GomaProperties(
                      goma_approach=common.GomaConfig.RBE_PROD,
                  ),
          }))

  yield api.test(
      'versioned',
      api.properties(
          **{
              '$chromeos/goma':
                  GomaProperties(
                      goma_approach=common.GomaConfig.RBE_PROD,
                  ),
          }),
      api.step_data(
          'init sdk.check SDK in named cache.read sdk cache state json',
          api.file.read_proto(SdkCacheState(version=2))))

  yield api.test(
      'with-changes',
      api.properties(
          **{
              '$chromeos/goma':
                  GomaProperties(
                      goma_approach=common.GomaConfig.RBE_PROD,
                  ),
          }),
      api.properties(
          TestInputProperties(
              gerrit_changes=[common_pb2.GerritChange(change=1234)])))

  yield api.test(
      'with-toolchain-changes',
      api.properties(
          **{
              '$chromeos/goma':
                  GomaProperties(
                      goma_approach=common.GomaConfig.RBE_PROD,
                  ),
          }),
      api.step_data(
          'init sdk.detect toolchain change.read output file',
          api.file.read_raw(
              content=PointlessBuildCheckResponse().SerializeToString())),
      api.properties(
          TestInputProperties(
              gerrit_changes=[common_pb2.GerritChange(change=1234)])))

  yield api.test(
      'with-toolchain-changes-and-force-no-toolchain-cls',
      api.properties(
          **{
              '$chromeos/goma':
                  GomaProperties(
                      goma_approach=common.GomaConfig.RBE_PROD,
                  ),
          }),
      api.step_data(
          'init sdk.detect toolchain change.read output file',
          api.file.read_raw(
              content=PointlessBuildCheckResponse().SerializeToString())),
      api.properties(
          **{'$chromeos/cros_sdk': {
              'force_off_toolchain_changed': True
          }}),
      api.properties(
          TestInputProperties(
              gerrit_changes=[common_pb2.GerritChange(change=1234)])))

  yield api.test(
      'failed-step-init-sdk',
      api.properties(
          **{
              '$chromeos/goma':
                  GomaProperties(
                      goma_approach=common.GomaConfig.RBE_PROD,
                  ),
          }),
      api.step_data(
          'init sdk.call chromite.api.SdkService/'
          'Create.call build API script', retcode=1),
      # Since create_chroot just downloads a tarball and unpacks it, we should
      # expect an INFRA_FAILURE when it fails.
      status='INFRA_FAILURE',
  )

  yield api.test(
      'failed-step-update-sdk',
      api.properties(
          **{
              '$chromeos/goma':
                  GomaProperties(
                      goma_approach=common.GomaConfig.RBE_PROD,
                  ),
          }),
      api.step_data(
          'update sdk.call chromite.api.SdkService/'
          'Update.call build API script', retcode=1),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.test(
      'no-chroot-link', api.cros_version.workspace_version('R118-98765.0.0'),
      api.properties(
          **{
              '$chromeos/goma':
                  GomaProperties(
                      goma_approach=common.GomaConfig.RBE_PROD,
                  ),
          }),
      api.post_check(post_process.DoesNotRun,
                     'link chroot in workspace.ensure workspace'))

  yield api.test(
      'failed-step-destroy-chroot-tests',
      api.cros_version.workspace_version('R113-45678.0.0'),
      api.properties(
          **{
              '$chromeos/goma':
                  GomaProperties(
                      goma_approach=common.GomaConfig.RBE_PROD,
                  ),
          }),
      api.step_data('link chroot in workspace.ensure workspace', retcode=1),
      # TODO (b/275363240): audit this test.
      status='INFRA_FAILURE',
  )

  yield api.test(
      'remaining-test-data',
      api.cros_sdk.is_chroot_usable([False, True]),
      api.properties(
          **{
              '$chromeos/goma':
                  GomaProperties(
                      goma_approach=common.GomaConfig.RBE_PROD,
                  ),
          }),
      api.post_check(post_process.StepFailure, 'clean up SDK chroot'),
      status='FAILURE',
  )

  yield api.test(
      'preload-does-not-exists', api.cros_sdk.preload_path_exists(False),
      api.properties(
          **{
              '$chromeos/goma':
                  GomaProperties(
                      goma_approach=common.GomaConfig.RBE_PROD,
                  ),
          }),
      api.post_check(post_process.DoesNotRun,
                     'configure chroot path.create preload path'))

  yield api.test(
      'no-goma', api.properties(**{
          '$chromeos/goma': GomaProperties(),
      }),
      api.properties(
          **{
              '$chromeos/remoteexec':
                  RemoteexecProperties(
                      reproxy_cfg_file='reclient_cfgs/reproxy_config.cfg')
          }), api.properties(TestInputProperties(check_remoteexec=True)))

  yield api.test(
      'use-remoteexec',
      api.properties(
          **{
              '$chromeos/remoteexec':
                  RemoteexecProperties(
                      reproxy_cfg_file='reclient_cfgs/reproxy_config.cfg')
          }), api.properties(TestInputProperties(check_remoteexec=True)))
