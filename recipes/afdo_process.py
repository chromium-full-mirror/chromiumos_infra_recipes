# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building an AFDO benchmark profile."""

DEPS = [
    'recipe_engine/properties',
    'build_menu',
    'cros_artifacts',
    'cros_sdk',
    'cros_version',
    'easy',
    'sysroot_util',
    'test_util',
]

from google.protobuf import json_format as json_pb

from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import ArtifactsByService
from PB.chromite.api.artifacts import PrepareForBuildResponse as Relevance
from PB.chromite.api.packages import GetTargetVersionsRequest
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipes.chromeos.afdo_process import AfdoProcessProperties
from PB.testplans.pointless_build import PointlessBuildCheckResponse

PROPERTIES = AfdoProcessProperties


def RunSteps(api, properties):
  build_target = properties.build_target
  with api.build_menu.configure_builder(build_target) as config:
    if config:
      DoRunSteps(api, config, build_target, properties)


def DoRunSteps(api, config, build_target, properties):
  # If we received any extra input_artifacts, add them to the values
  # from the config.
  config.artifacts.artifacts_info.toolchain.input_artifacts.extend(
      properties.input_artifacts or [])

  relevance = api.build_menu.setup_workspace_and_chroot(
      artifact_build=True, forced_relevant=properties.force_relevant_build)
  if relevance == Relevance.POINTLESS:
    return

  # This update_for_artifact_build call will download the input artifacts into
  # the chroot.  This builder is only appropriate to use if there are no package
  # builds needed prior to making artifacts, and those artifacts will be created
  # by the appropriate Build API Bundle() calls in upload_artifacts (below).
  api.sysroot_util.update_for_artifact_build(api.cros_sdk.chroot,
                                             config.artifacts,
                                             force_relevance=True,
                                             name='prepare artifacts final')

  api.cros_artifacts.upload_artifacts(
      config.id.name, build_target, config.id.type,
      config.artifacts.artifacts_gs_bucket,
      artifacts_info=config.artifacts.artifacts_info, sysroot=None,
      chroot=api.cros_sdk.chroot)


def GenTests(api):

  yield api.test(
      'basic',
      api.test_util.test_build(builder='benchmark-afdo-process').build)

  yield api.test(
      'changes',
      api.test_util.test_build(cq=True, builder='benchmark-afdo-process').build)

  yield api.test(
      'pointless',
      api.test_util.test_build(builder='benchmark-afdo-process').build,
      api.build_menu.set_build_api_return('prepare artifacts',
                                          'ArtifactsService/PrepareForBuild',
                                          '{"build_relevance": "POINTLESS"}'))

  yield api.test(
      'with-input-artifacts',
      api.test_util.test_build(builder='benchmark-afdo-process').build,
      api.properties(input_artifacts=[{
          'artifact_types': [ArtifactsByService.Toolchain.CHROME_DEBUG_BINARY],
          'gs_locations': ['chromeos-image-archive/BUILDER/VERSION-BUILD_ID']
      }]))

  yield api.test('builder-no-longer-exists',
                 api.test_util.test_build(builder='no-such-builder').build)
