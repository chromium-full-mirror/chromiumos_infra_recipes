# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'cros_infra_config',
]

from google.protobuf import json_format

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2


def RunSteps(api):
  commit = api.buildbucket.gitiles_commit
  changes = api.buildbucket.build.input.gerrit_changes
  config = api.cros_infra_config.configure_builder(commit=commit,
                                                   changes=changes)
  api.assertions.assertEqual(config, api.cros_infra_config.config)

  expected = [
      json_format.MessageToDict(x) for x in config.orchestrator.gerrit_changes
  ] + [json_format.MessageToDict(x) for x in changes]
  result = [
      json_format.MessageToDict(x) for x in api.cros_infra_config.gerrit_changes
  ]

  api.assertions.assertEqual(expected, result)


def GenTests(api):

  def buildbucket_build(project='chromeos', bucket='toolchain',
                        builder='toolchain-orchestrator', tags=None,
                        revision='2d72510e447ab60a9728aeea2362d8be2cbd7789',
                        cls=None):
    build = api.buildbucket.ci_build_message(project=project, bucket=bucket,
                                             builder=builder, tags=tags,
                                             revision=revision)
    build.input.gerrit_changes.extend(cls or [])
    return api.buildbucket.build(build)

  yield api.test('basic', buildbucket_build())

  yield api.test('with_changes',
                 buildbucket_build(cls=[common_pb2.GerritChange(change=1234)]))
