# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building an AFDO benchmark profile."""

from typing import List, Optional

from google.protobuf.json_format import MessageToDict

from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import ArtifactsByService
from PB.recipes.chromeos.afdo_process import AfdoProcessProperties

DEPS = [
    'build_menu',
    'cros_sdk',
    'sysroot_util',
    'test_util',
]


PROPERTIES = AfdoProcessProperties


def RunSteps(api: RecipeApi, properties: AfdoProcessProperties):
  with api.build_menu.configure_builder() as config, \
      api.build_menu.setup_workspace_and_chroot() as is_relevant:
    if is_relevant:
      DoRunSteps(api, config, properties)


def DoRunSteps(api: RecipeApi, config: BuilderConfig,
               properties: AfdoProcessProperties):
  # If we received any extra input_artifacts, add them to the values
  # from the config.
  config.artifacts.artifacts_info.toolchain.input_artifacts.extend(
      properties.input_artifacts or [])

  # This update_for_artifact_build call will download the input artifacts into
  # the chroot.  This builder is only appropriate to use if there are no package
  # builds needed prior to making artifacts, and those artifacts will be created
  # by the appropriate Build API Bundle() calls in upload_artifacts (below).
  api.sysroot_util.update_for_artifact_build(api.cros_sdk.chroot,
                                             config.artifacts,
                                             force_relevance=True,
                                             name='prepare artifacts final')

  api.build_menu.upload_artifacts(config)


def GenTests(api: RecipeTestApi):

  def test(name: str, builder: str = 'benchmark-afdo-process',
           input_artifacts: Optional[List[
               ArtifactsByService.Toolchain.ArtifactInfo]] = None,
           artifact_pointless: bool = False, **kwargs) -> TestData:
    status = kwargs.pop('status', 'SUCCESS')
    kwargs['builder'] = builder

    afdo_props = AfdoProcessProperties(artifact_build=True)
    for artifact in input_artifacts or []:
      afdo_props.input_artifacts.add().CopyFrom(artifact)
    input_props = MessageToDict(afdo_props, preserving_proto_field_name=True)
    input_props.update(api.test_util.build_menu_properties(artifact_build=True))

    ret = api.test_util.test_child_build('chell', input_properties=input_props,
                                         **kwargs).build
    if artifact_pointless:
      ret += api.build_menu.set_build_api_return(
          'prepare artifacts', 'ArtifactsService/BuildSetup',
          '{"build_relevance": "POINTLESS"}')
    return api.test(name, ret, status=status)

  input_artifact = ArtifactsByService.Toolchain.ArtifactInfo(
      artifact_types=[ArtifactsByService.Toolchain.CHROME_DEBUG_BINARY],
      gs_locations=['chromeos-image-archive/BUILDER/VERSION-BUILD_ID'])

  yield test('basic')

  yield test('changes', cq=True)

  yield test('pointless', artifact_pointless=True)

  yield test('with-input-artifacts', input_artifacts=[input_artifact])

  # TODO (b/275363240): audit this test.
  yield test('builder-no-longer-exists', builder='no-such-builder',
             status='FAILURE')
