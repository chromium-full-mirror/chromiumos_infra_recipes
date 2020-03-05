# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/buildbucket',
    'cros_build_support',
]

from PB.chromiumos import common
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2


def RunSteps(api):
  # This relies on the builder name being '${TARGET}-cq' in the tests below.
  # See also amd64-generic-cq and grunt-unittest-only-cq for some examples of
  # where this would break.
  # DO NOT EXTRACT THIS WAY IN LIVE CODE.
  name = api.buildbucket.build.builder.builder.split('-',1)[0]
  target = common.BuildTarget(name=name)

  commit = api.buildbucket.gitiles_commit
  changes = api.buildbucket.build.input.gerrit_changes

  config = api.cros_build_support.configure_builder(
      target, commit=commit, changes=changes)
  if not config:
    return
  with api.cros_build_support.setup_workspace():
    api.cros_build_support.sync_to_commit()
    api.cros_build_support.apply_changes()
    want = changes if config.build.apply_gerrit_changes and changes else []
    assert len(want) == len(api.cros_build_support.patch_sets)

def GenTests(api):
  def buildbucket_build(
      project='chromeos', bucket='cq', builder='atlas-cq', tags=None,
      revision='2d72510e447ab60a9728aeea2362d8be2cbd7789', cls=None):
    if revision:
      build = api.buildbucket.ci_build_message(
          project=project, bucket=bucket, builder=builder, tags=tags,
          revision=revision)
      if cls:
        build.input.gerrit_changes.extend(cls)
    elif cls:
      # There's always an extra CL on the front, thanks to try_build_message.
      build = api.buildbucket.try_build_message(
          project=project, bucket=bucket, builder=builder, tags=tags)
      build.input.gerrit_changes.extend(cls)
    else:
      return api.buildbucket.generic_build(
          project=project, bucket=bucket, builder=builder, tags=tags)
    return api.buildbucket.build(build)

  yield api.test('basic') + buildbucket_build()

  yield (api.test('has_changes') + #
         buildbucket_build(cls=[common_pb2.GerritChange(change=1234)]))

  yield (api.test('apply_gerrit_changes_false') + #
         buildbucket_build(builder='grunt-postsubmit',
                           cls=[common_pb2.GerritChange(change=1234)]))

  yield (api.test('has_changes_and_no_commit') + #
         buildbucket_build(
             revision=None, cls=[common_pb2.GerritChange(change=1234)]))

  yield (api.test('has_no_commit_and_no_changes') + #
         buildbucket_build(revision=None))

  yield (api.test('has_parent') + #
         buildbucket_build(tags=[
             {'key': 'parent_buildbucket_id', 'value': 'parent_id'},
         ]))

  yield api.test('missing_config') + buildbucket_build(builder='nosuch-cq')
