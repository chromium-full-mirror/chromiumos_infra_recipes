# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf import json_format

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.cros_infra_config.tests.test import TestInputProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_infra_config',
    'test_util',
]


PROPERTIES = TestInputProperties


def RunSteps(api, properties):
  commit = api.buildbucket.gitiles_commit
  changes = api.buildbucket.build.input.gerrit_changes
  config = api.cros_infra_config.configure_builder(commit=commit,
                                                   changes=changes)
  api.assertions.assertEqual(config, api.cros_infra_config.config)
  api.assertions.assertEqual(
      api.cros_infra_config.safe_get_builder_configs(['abc']), {})

  api.assertions.assertEqual(
      len(api.cros_infra_config.gerrit_changes),
      properties.expected_change_count)

  expected = [
      json_format.MessageToDict(x) for x in config.orchestrator.gerrit_changes
  ]
  expected.extend(
      json_format.MessageToDict(c)
      for c in changes
      if json_format.MessageToDict(c) not in expected)
  result = [
      json_format.MessageToDict(x) for x in api.cros_infra_config.gerrit_changes
  ]

  api.assertions.assertEqual(expected, result)


def GenTests(api):

  def expected_changes(count):
    return api.properties(TestInputProperties(expected_change_count=count))

  yield api.test('basic',
                 api.test_util.test_child_build('amd64-generic', cq=True).build,
                 expected_changes(1))

  yield api.test('postsubmit',
                 api.test_util.test_child_build('amd64-generic').build)

  yield api.test(
      'with-changes',
      api.test_util.test_orchestrator(
          bucket='toolchain',
          extra_changes=[common_pb2.GerritChange(change=1234)]).build,
      expected_changes(2))

  yield api.test(
      'with-duplicate-change',
      api.test_util.test_orchestrator(
          bucket='toolchain', extra_changes=[
              common_pb2.GerritChange(
                  host='chromium-review.googlesource.com',
                  project='chromiumos/overlays/chromiumos-overlay',
                  change=1394249, patchset=-1)
          ]).build, expected_changes(1))
