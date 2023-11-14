# -*- coding: utf-8 -*-

# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'build_plan',
    'cros_infra_config',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  child_specs = api.cros_infra_config.get_builder_config(
      'postsubmit-orchestrator').orchestrator.child_specs
  completed_builds, new_requests = api.build_plan.get_build_plan(
      child_specs, True, [], common_pb2.GitilesCommit(),
      common_pb2.GitilesCommit())
  api.assertions.assertEqual(completed_builds, [])
  # This test depends on the number of children in cros_infra_config.test_api.
  api.assertions.assertEqual(len(new_requests), 3)


def GenTests(api):
  yield api.test(
      'basic',
      api.buildbucket.ci_build(project='chromeos', bucket='bisect',
                               builder='bisect-orchestrator'),
  )
