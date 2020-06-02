# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_infra_config',
    'test_util',
]

from PB.chromiumos import common
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.cros_infra_config.examples.builder import (
    BuilderProperties)

PROPERTIES = BuilderProperties


def RunSteps(api, properties):
  target = properties.build_target
  commit = api.buildbucket.gitiles_commit
  changes = api.buildbucket.build.input.gerrit_changes

  config = api.cros_infra_config.configure_builder(commit=commit,
                                                   changes=changes)
  api.assertions.assertEqual(config, api.cros_infra_config.config)

  builder = config.id.name if config else 'nosuch-cq'
  api.assertions.assertEqual(properties.builder, builder)
  if not config:
    return

  if not commit.project:
    commit = common_pb2.GitilesCommit(host='chrome-internal.googlesource.com',
                                      project='chromeos/manifest-internal',
                                      id='abcd1234', ref='refs/heads/snapshot')
  api.assertions.assertEqual(commit, api.cros_infra_config.gitiles_commit)
  want = [] if not (changes and config.build.apply_gerrit_changes) else changes
  api.assertions.assertEqual(want, api.cros_infra_config.gerrit_changes)

  # Force a reload of the config.
  api.assertions.assertEqual(config, api.cros_infra_config.fresh_config)


def GenTests(api):

  def builder(build_target='amd64-generic', **kwargs):
    kwargs['exe'] = common_pb2.Executable(cipd_package='CIPD_PACKAGE',
                                          cipd_version='prod')
    build = api.test_util.test_build(**kwargs)
    return build.build + api.properties(
        BuilderProperties(builder=build.message.builder.builder,
                          build_target=common.BuildTarget(name=build_target)))

  yield api.test('basic', builder())

  yield api.test('cq-build', builder(cq=True))

  yield api.test(
      'apply_gerrit_changes_false',
      builder(build_target='grunt', builder='grunt-postsubmit',
              extra_changes=[common_pb2.GerritChange(change=1234)]))

  yield api.test(
      'has_changes_and_no_commit',
      builder(revision=None,
              extra_changes=[common_pb2.GerritChange(change=1234)]))

  yield api.test('has_no_commit_and_no_changes', builder(revision=None))

  yield api.test(
      'has_parent',
      builder(tags=[
          {
              'key': 'parent_buildbucket_id',
              'value': 'parent_id'
          },
      ]))

  yield api.test('missing_config',
                 builder(build_target='nosuch', builder='nosuch-cq'))
