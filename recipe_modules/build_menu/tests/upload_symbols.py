# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for the upload_symbols function."""

from PB.chromiumos import common as common_pb2
from PB.chromiumos.builder_config import BuilderConfig
from PB.recipe_modules.chromeos.build_menu.tests.test import TestProperties
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'build_menu',
]

PROPERTIES = TestProperties


def RunSteps(api, properties):
  artifact_types = [common_pb2.ArtifactsByService.Sysroot.SIMPLE_CHROME_SYSROOT]
  if properties.include_symbols:
    artifact_types.append(common_pb2.ArtifactsByService.Sysroot.DEBUG_SYMBOLS)

  config = BuilderConfig(
      id=BuilderConfig.Id(name='amd64-generic-cq', type=BuilderConfig.Id.CQ),
      artifacts=BuilderConfig.Artifacts(
          artifacts_info=common_pb2.ArtifactsByService(
              sysroot=common_pb2.ArtifactsByService.Sysroot(output_artifacts=[
                  common_pb2.ArtifactsByService.Sysroot.ArtifactInfo(
                      artifact_types=artifact_types, gs_locations=[
                          'chromeos-image-archive/{target}-cq/{version}'
                      ])
              ]),
          )))

  uploaded, _ = api.build_menu.upload_symbols(config)

  if properties.include_symbols:
    api.assertions.assertIsNotNone(uploaded)
  else:
    api.assertions.assertIsNone(uploaded)


def GenTests(api):

  yield api.test('upload-symbols',
                 api.properties(TestProperties(include_symbols=True)),
                 api.post_check(post_process.MustRun, 'upload symbols'),
                 api.post_process(post_process.DropExpectation))

  yield api.test('no-symbols',
                 api.properties(TestProperties(include_symbols=False)),
                 api.post_check(post_process.DoesNotRun, 'upload symbols'),
                 api.post_process(post_process.DropExpectation))
