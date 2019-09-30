# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.chromiumos.builder_config import BuilderConfig
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as bbcommon_pb2
from recipe_engine.recipe_api import Property

DEPS = [
    'cros_relevance',
    'recipe_engine/assertions',
    'recipe_engine/properties',
]

PROPERTIES = {
    'expected_builders':
        Property(kind=list, help='List of builder names', default=[])
}

def RunSteps(api, expected_builders):
  gc = [bbcommon_pb2.GerritChange(change=123),
        bbcommon_pb2.GerritChange(change=456)]
  bc = [BuilderConfig(
      id=BuilderConfig.Id(
          name='my little builder',
      ),
      general=BuilderConfig.General(
          run_when=BuilderConfig.General.RunWhen(
              mode=BuilderConfig.General.RunWhen.ALWAYS_RUN,
          ),
      ),
  )]
  builders = api.cros_relevance.get_necessary_builders(
      bc, gc, bbcommon_pb2.GitilesCommit())
  api.assertions.assertItemsEqual(builders, expected_builders)

def GenTests(api):
  builder = 'builder'
  build_config = [dict(build_target='build_target')]
  yield (api.test('skip_all_builds') +
         api.cros_relevance.simulate_run_build_planner(
             builder_ids=[]) +
         api.properties(expected_builders=[]))
  yield (api.test('keep_a_build') +
         api.cros_relevance.simulate_run_build_planner(
             builder_ids=[BuilderConfig.Id(name='my little builder')]) +
         api.properties(expected_builders=['my little builder']))
