# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import BuildTarget
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import builder_common as builder_common_pb2
from PB.recipe_modules.chromeos.cros_artifacts.tests.artifacts_gs_path import ArtifactsGsPathProperties

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_artifacts',
]


PROPERTIES = ArtifactsGsPathProperties


def RunSteps(api, properties):
  upload_path = api.cros_artifacts.artifacts_gs_path(
      properties.builder_name, target=BuildTarget(name=properties.target_name),
      kind=properties.builder_type, template=properties.template)
  expected = properties.expected_upload_path
  if '{time}' in properties.template:
    expected = expected % api.cros_artifacts.timestamp_micros
  api.assertions.assertEqual(upload_path, expected)


def GenTests(api):

  yield api.test(
      'release-prod',
      api.buildbucket.build(
          build_pb2.Build(
              id=1234,
          ),
      ),
      api.properties(
          ArtifactsGsPathProperties(
              builder_name='atlas-kernelnext-release-main',
              target_name='atlas-kernelnext',
              builder_type=BuilderConfig.Id.RELEASE,
              expected_upload_path='atlas-kernelnext-release/R99-1234.56.0-101-%s',
              template='{target}-release/{version}-{time}')),
  )

  yield api.test(
      'release-staging',
      api.buildbucket.build(
          build_pb2.Build(
              id=5678,
              builder=builder_common_pb2.BuilderID(bucket='staging'),
          ),
      ),
      api.properties(
          ArtifactsGsPathProperties(
              builder_name='eve-staging-release-main', target_name='eve',
              builder_type=BuilderConfig.Id.RELEASE,
              expected_upload_path='eve-staging-release-main/R99-1234.56.0-101-5678'
          ),
      ))

  yield api.test(
      'non-release', api.buildbucket.build(
          build_pb2.Build(
              id=4321,
          ),
      ),
      api.properties(
          ArtifactsGsPathProperties(
              builder_name='eve-cq', target_name='eve',
              builder_type=BuilderConfig.Id.CQ,
              expected_upload_path='eve-cq/R99-1234.56.0-101-4321')))

  yield api.test(
      'led',
      api.buildbucket.build(
          build_pb2.Build(
              id=0,
          ),
      ),
      api.properties(
          ArtifactsGsPathProperties(
              builder_name='eve-staging-release-main', target_name='eve',
              builder_type=BuilderConfig.Id.RELEASE,
              expected_upload_path='eve-staging-release-main/R99-1234.56.0-101-led_user_example.com_deadbeef'
          ), **{
              '$recipe_engine/led': {
                  'led_run_id': 'led/user_example.com/deadbeef'
              }
          }),
      api.post_process(post_process.DropExpectation),
  )
