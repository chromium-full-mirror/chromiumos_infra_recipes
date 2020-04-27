# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/file',
    'recipe_engine/properties',
    'cros_infra_config',
    'repo',
    'workspace_util',
]

from PB.chromiumos import common
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.workspace_util.examples.test import (
    TestInputProperties)
from PB.testplans.pointless_build import PointlessBuildCheckResponse

PROPERTIES = TestInputProperties


def RunSteps(api, properties):
  target = properties.build_target
  commit = api.buildbucket.gitiles_commit
  changes = api.buildbucket.build.input.gerrit_changes

  # Configure the builder so that we have
  # self.m.cros_infra_config.gitiles_commit. All of our tests will be with
  # builders that have configs.
  config = api.cros_infra_config.configure_builder(commit=commit,
                                                   changes=changes)
  with api.workspace_util.sync_to_manifest_groups(['group1', 'group2'],
                                                  api.repo.LocalManifest(
                                                      repo='http://repo.url',
                                                      path='manifest_path')):
    api.workspace_util.apply_changes()

  api.workspace_util.detect_toolchain_cls(None)
  api.assertions.assertEqual(properties.toolchain_cls_applied,
                             api.workspace_util.toolchain_cls_applied)


def GenTests(api):

  def buildbucket_build(project='chromeos', bucket='cq', builder='atlas-cq',
                        build_target='atlas', tags=None,
                        revision='2d72510e447ab60a9728aeea2362d8be2cbd7789',
                        cls=None, toolchain_cls_applied=False):
    build = api.buildbucket.ci_build_message(project=project, bucket=bucket,
                                             builder=builder, tags=tags,
                                             revision=revision)
    if not revision:
      build.input.gitiles_commit.Clear()
    if cls:
      build.input.gerrit_changes.extend(cls)
    ret = api.buildbucket.build(build)
    ret += api.properties(
        TestInputProperties(
            build_target=common.BuildTarget(name=build_target), builder=builder,
            toolchain_cls_applied=toolchain_cls_applied))
    if cls:
      resp = PointlessBuildCheckResponse()
      resp.build_is_pointless.value = not toolchain_cls_applied
      ret += api.step_data(
          'detect toolchain change.path relevancy check.read output file',
          api.file.read_raw(content=resp.SerializeToString()))
    return ret

  yield api.test('basic', buildbucket_build())

  yield api.test('has_changes',
                 buildbucket_build(cls=[common_pb2.GerritChange(change=1234)]))

  yield api.test(
      'has_changes_and_no_commit',
      buildbucket_build(revision=None,
                        cls=[common_pb2.GerritChange(change=1234)]))

  yield api.test('has_no_commit_and_no_changes',
                 buildbucket_build(revision=None))

  yield api.test(
      'has_toolchain_changes',
      buildbucket_build(cls=[common_pb2.GerritChange(change=1234)],
                        toolchain_cls_applied=True))
