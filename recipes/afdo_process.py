# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building an AFDO benchmark profile."""

DEPS = [
    'build_menu',
    'cros_artifacts',
    'cros_sdk',
    'sysroot_util',
    'test_util',
]

from PB.chromiumos.common import ArtifactsByService
from PB.chromiumos.common import BuildTarget
from PB.recipes.chromeos.afdo_process import AfdoProcessProperties

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

  if not api.build_menu.setup_workspace_and_chroot(
      artifact_build=True, forced_relevant=properties.force_relevant_build):
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

  def test(name, builder='benchmark-afdo-process', input_artifacts=None,
           artifact_pointless=False, **kwargs):
    kwargs['builder'] = builder
    if input_artifacts:
      kwargs['input_properties'] = AfdoProcessProperties(
          input_artifacts=input_artifacts)
    ret = api.test_util.test_child_build('chell', **kwargs).build
    if artifact_pointless:
      ret += api.build_menu.set_build_api_return(
          'prepare artifacts', 'ArtifactsService/PrepareForBuild',
          '{"build_relevance": "POINTLESS"}')
    return api.test(name, ret)

  input_artifact = ArtifactsByService.Toolchain.ArtifactInfo(
      artifact_types=[ArtifactsByService.Toolchain.CHROME_DEBUG_BINARY],
      gs_locations=['chromeos-image-archive/BUILDER/VERSION-BUILD_ID'])

  yield test('basic')

  yield test('changes', cq=True)

  yield test('pointless', artifact_pointless=True)

  yield test('with-input-artifacts', input_artifacts=[input_artifact])

  yield test('builder-no-longer-exists', builder='no-such-builder')
