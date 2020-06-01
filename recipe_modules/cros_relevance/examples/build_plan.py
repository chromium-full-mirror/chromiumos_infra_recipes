# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_relevance',
]

from PB.chromiumos.builder_config import BuilderConfig
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as bbcommon_pb2
from PB.recipe_modules.chromeos.cros_relevance.examples.build_plan import (
    BuildPlanTest)

PROPERTIES = BuildPlanTest
_BUILDER_NAME = 'my little builder'


def RunSteps(api, properties):
  gc = [
      bbcommon_pb2.GerritChange(change=123),
      bbcommon_pb2.GerritChange(change=456)
  ]
  bc = [
      BuilderConfig(
          id=BuilderConfig.Id(name=_BUILDER_NAME),
          general=BuilderConfig.General(
              run_when=BuilderConfig.General.RunWhen(
                  mode=BuilderConfig.General.RunWhen.ALWAYS_RUN,
              )))
  ]
  builders = api.cros_relevance.get_necessary_builders(
      bc, gc, bbcommon_pb2.GitilesCommit(id='hello'),
      properties.test_builder_ids)
  api.assertions.assertItemsEqual(builders, properties.expected_builders)


def GenTests(api):
  yield api.test('basic')

  yield api.test(
      'my-little-builder',
      api.properties(
          BuildPlanTest(test_builder_ids=[BuilderConfig.Id(name=_BUILDER_NAME)],
                        expected_builders=[_BUILDER_NAME])))
