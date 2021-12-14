# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'build_menu',
    'cros_release',
    'git',
    'test_util',
]

from recipe_engine import post_process

from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos import common as common_pb2
from PB.chromite.api.sysroot import Sysroot
from PB.recipe_modules.chromeos.cros_release.cros_release import CrosReleaseProperties
from PB.recipe_modules.chromeos.cros_version.cros_version import CrosVersionProperties
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2


def RunSteps(api):

  api.cros_release.create_releasespec()
  api.assertions.assertIsNotNone(api.cros_release.releasespec)

  api.cros_release.create_releasespec(gs_location='bucket/foo/')
  api.assertions.assertIsNotNone(api.cros_release.releasespec)

  api.cros_release.create_releasespec(gs_location='bucket/foo/bar.xml')
  api.assertions.assertIsNotNone(api.cros_release.releasespec)

  api.assertions.assertEqual(
      api.cros_release.channel_strip_prefix(common_pb2.Channel.CHANNEL_BETA),
                                            'beta')
  api.assertions.assertEqual(
      api.cros_release.channel_dash_suffix(common_pb2.Channel.CHANNEL_BETA),
                                           'beta-channel')

  # Manufacture the minimal builder config.
  config = BuilderConfig(
      id=BuilderConfig.Id(name='amd64-generic-release',
                          type=BuilderConfig.Id.RELEASE),
      artifacts=BuilderConfig.Artifacts(
          artifacts_info=common_pb2.ArtifactsByService(
              legacy=common_pb2.ArtifactsByService.Legacy(output_artifacts=[
                  common_pb2.ArtifactsByService.Legacy
                  .ArtifactInfo(gs_locations=[
                      'chromeos-image-archive/{target}-release-rubik/{version}'
                  ])
              ]),
          )))
  sysroot = Sysroot(build_target=common_pb2.BuildTarget(name='amd64-generic'))

  api.cros_release.push_and_sign_images(config, sysroot)
  api.cros_release.schedule_payload_generation()


def GenTests(api):
  yield api.build_menu.test(
      'basic',
      api.properties(
          **{
              '$chromeos/cros_version':
                  CrosVersionProperties(remove_snapshot_from_version=True),
          }), api.git.diff_check(True),
      api.post_check(
          post_process.LogContains,
          'push images.call chromite.api.ImageService/PushImage', 'request', [
              'gs://chromeos-image-archive/amd64-generic-release-rubik/R99-1234.56.0'
          ]),
      api.test_util.test_child_build('amd64-generic').build)

  yield api.build_menu.test(
      'channel_rubik',
      api.properties(
          **{
              '$chromeos/cros_version':
                  CrosVersionProperties(remove_snapshot_from_version=True),
              '$chromeos/cros_release':
                  CrosReleaseProperties(channels=[common_pb2.CHANNEL_RUBIK]),
          }),
      api.post_check(
          post_process.LogContains,
          'push images.call chromite.api.ImageService/PushImage', 'request', [
              'gs://chromeos-image-archive/amd64-generic-release-rubik/R99-1234.56.0'
          ]),
      api.test_util.test_child_build('amd64-generic').build)

  yield api.build_menu.test(
      'paygen_failure',
      api.properties(
          **{
              '$chromeos/cros_version':
                  CrosVersionProperties(remove_snapshot_from_version=True),
              '$chromeos/cros_release':
                  CrosReleaseProperties(channels=[common_pb2.CHANNEL_RUBIK]),
          }),
      api.post_check(
          post_process.LogContains,
          'push images.call chromite.api.ImageService/PushImage', 'request', [
              'gs://chromeos-image-archive/amd64-generic-release-rubik/R99-1234.56.0'
          ]),
      api.buildbucket.simulated_collect_output(
          [build_pb2.Build(id=8922054662172514000, status='FAILURE')],
          'generate payloads.running paygen orchestrator.collect'),
      api.post_check(post_process.StepFailure, 'generate payloads'),
      api.test_util.test_child_build('amd64-generic').build)
