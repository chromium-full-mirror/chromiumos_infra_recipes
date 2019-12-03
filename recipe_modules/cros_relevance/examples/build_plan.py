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


def RunSteps(api):
  gc = [
      bbcommon_pb2.GerritChange(change=123),
      bbcommon_pb2.GerritChange(change=456)
  ]
  bc = [
      BuilderConfig(
          id=BuilderConfig.Id(name='my little builder',),
          general=BuilderConfig.General(
              run_when=BuilderConfig.General.RunWhen(
                  mode=BuilderConfig.General.RunWhen.ALWAYS_RUN,),),
      )
  ]
  builders = api.cros_relevance.get_necessary_builders(
      bc, gc, bbcommon_pb2.GitilesCommit(id='hello'), test_builder_ids=[])
  api.assertions.assertItemsEqual(builders, [])
  builders = api.cros_relevance.get_necessary_builders(
      bc, gc, bbcommon_pb2.GitilesCommit(id='hello'),
      test_builder_ids=[BuilderConfig.Id(name='my little builder')])
  api.assertions.assertItemsEqual(builders, ['my little builder'])


def GenTests(api):
  yield (api.test('build_plan'))
