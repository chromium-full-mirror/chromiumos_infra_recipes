# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'config_util',
]

from PB.chromiumos import common
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.config_util.examples.test import (
    TestInputProperties)

PROPERTIES = TestInputProperties


def RunSteps(api, properties):
  target = properties.build_target
  commit = api.buildbucket.gitiles_commit
  changes = api.buildbucket.build.input.gerrit_changes

  config = api.config_util.configure_builder(target, commit=commit,
                                             changes=changes)
  builder = config.id.name if config else 'nosuch-cq'
  api.assertions.assertEqual(properties.builder, builder)
  if not config:
    return

  if not commit.project:
    commit = common_pb2.GitilesCommit(host='chrome-internal.googlesource.com',
                                      project='chromeos/manifest-internal',
                                      id='abcd1234', ref='refs/heads/snapshot')
  api.assertions.assertEqual(commit, api.config_util.gitiles_commit)
  want = [] if not (changes and config.build.apply_gerrit_changes) else changes
  api.assertions.assertEqual(want, api.config_util.gerrit_changes)


def GenTests(api):

  def buildbucket_build(
      project='chromeos', bucket='cq', builder='atlas-cq', build_target='atlas',
      tags=None, revision='2d72510e447ab60a9728aeea2362d8be2cbd7789', cls=None):
    build = api.buildbucket.ci_build_message(project=project, bucket=bucket,
                                             builder=builder, tags=tags,
                                             revision=revision)
    if not revision:
      build.input.gitiles_commit.Clear()
    if cls:
      build.input.gerrit_changes.extend(cls)
    if build_target:
      build_target = common.BuildTarget(name=build_target)
    return (
        api.buildbucket.build(build) +  #
        api.properties(
            TestInputProperties(builder=builder, build_target=build_target)))

  yield api.test('basic') + buildbucket_build()

  yield (api.test('has_changes') +  #
         buildbucket_build(cls=[common_pb2.GerritChange(change=1234)]))

  yield (api.test('apply_gerrit_changes_false') +  #
         buildbucket_build(builder='grunt-postsubmit', build_target='grunt',
                           cls=[common_pb2.GerritChange(change=1234)]))

  yield (api.test('has_changes_and_no_commit') +  #
         buildbucket_build(revision=None,
                           cls=[common_pb2.GerritChange(change=1234)]))

  yield (api.test('has_no_commit_and_no_changes') +  #
         buildbucket_build(revision=None))

  yield (api.test('has_parent') +  #
         buildbucket_build(tags=[
             {
                 'key': 'parent_buildbucket_id',
                 'value': 'parent_id'
             },
         ]))

  yield (api.test('missing_config') +  #
         buildbucket_build(builder='nosuch-cq', build_target='nosuch'))

  yield (
      api.test('orchestrator') +  #
      buildbucket_build(builder='postsubmit-orchestrator', build_target=None))
