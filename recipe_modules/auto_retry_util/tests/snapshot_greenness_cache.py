# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests caching greenness for a specific snapshot and from looks for green."""

from recipe_engine import post_process

from PB.chromiumos.builder_config import BuilderConfigs
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import builder_common as builder_common_pb2
from PB.recipe_modules.chromeos.auto_retry_util.auto_retry_util import AutoRetryUtilProperties
from PB.recipe_modules.chromeos.auto_retry_util.auto_retry_util import ExperimentalFeature
from RECIPE_MODULES.chromeos.auto_retry_util.api import EXPERIMENTAL_FEATURE_WAITS_FOR_GREEN

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'auto_retry_util',
    'cros_infra_config',
    'test_util',
]



def RunSteps(api):
  child_build_info = [
      {
          'builder': {
              'builder': 'builder1-cq'
          },
          'status': 'FAILURE',
          'relevant': True
      },
  ]

  # Create 3 candidate builds, the first two used snapshot abc, the second two
  # used snapshot def.
  candidates = []
  for i in range(3):
    candidate = build_pb2.Build()
    candidate.output.properties['child_build_info'] = child_build_info
    candidate.output.properties['looks_for_green'] = {
        'status': 'STATUS_FOUND_NONE'
    }
    candidate.output.gitiles_commit.id = 'abc' if i < 2 else 'def'
    candidates.append(candidate)

  for b in candidates:
    api.auto_retry_util.analyze_build_failures(b)


def GenTests(api):

  configs = BuilderConfigs()
  orch = configs.builder_configs.add()
  orch.id.name = 'cq-orchestrator'
  orch.orchestrator.child_specs.add().name = 'builder1-cq'

  GREENNESS_PUBLISHED_SNAPSHOT_BUILD = build_pb2.Build(
      builder=builder_common_pb2.BuilderID(
          project='chromeos',
          bucket='postsubmit',
          builder='snapshot-orchestrator',
      ),
  )
  GREENNESS_PUBLISHED_SNAPSHOT_BUILD.output.properties['greenness'] = {
      'aggregateMetric': 100,
      'aggregateBuildMetric': 100,
  }
  GREENNESS_PUBLISHED_SNAPSHOT_BUILD.output.properties['local_greenness'] = {
      'greenness': {
          'builder1-snapshot': [100, 100, True, True]
      }
  }

  yield api.test(
      'greenness cache used',
      api.cros_infra_config.override_builder_configs_test_data(configs),
      api.properties(
          **{
              '$chromeos/auto_retry_util':
                  AutoRetryUtilProperties(experimental_features=[
                      ExperimentalFeature(
                          name=EXPERIMENTAL_FEATURE_WAITS_FOR_GREEN)
                  ])
          }),
      # Search for snapshot abc returns a green snapshot.
      api.buildbucket.simulated_search_results(
          [
              GREENNESS_PUBLISHED_SNAPSHOT_BUILD,
          ],
          'analyzing build results.get now green builders.get tot failure builders.buildbucket.search',
      ),
      api.post_process(
          post_process.LogContains,
          'analyzing build results.get now green builders.get tot failure builders.buildbucket.search',
          'request',
          [
            '"predicate": {\n          "builder": {\n            "bucket": "postsubmit",\n            "builder": "snapshot-orchestrator",\n            "project": "chromeos"\n          },'\
            '\n          "tags": [\n            {\n              "key": "buildset",\n              "value": "commit/gitiles/chrome-internal.googlesource.com/chromeos/manifest-internal/+/abc"\n            }\n          ]\n        }'
          ],
      ),
      # Don't search for snapshot abc again.
      api.post_process(
          post_process.DoesNotRun,
          'analyzing build results (2).get now green builders.get tot failure builders.buildbucket.search',
      ),
      # Search for snapshot def also returns a green snapshot.
      api.buildbucket.simulated_search_results(
          [
              GREENNESS_PUBLISHED_SNAPSHOT_BUILD,
          ],
          'analyzing build results (3).get now green builders.get tot failure builders.buildbucket.search',
      ),
      api.post_process(
          post_process.LogContains,
          'analyzing build results (3).get now green builders.get tot failure builders.buildbucket.search',
          'request',
          [
            '"predicate": {\n          "builder": {\n            "bucket": "postsubmit",\n            "builder": "snapshot-orchestrator",\n            "project": "chromeos"\n          },'\
            '\n          "tags": [\n            {\n              "key": "buildset",\n              "value": "commit/gitiles/chrome-internal.googlesource.com/chromeos/manifest-internal/+/def"\n            }\n          ]\n        }'
          ],
      ),
      # Don't do a second call for the lfg snapshot.
      api.post_process(
          post_process.DoesNotRun,
          'analyzing build results (2).get now green builders.find green snapshot',
      ),
      api.post_process(post_process.DropExpectation),
  )

  GREENNESS_MISSING_SNAPSHOT_BUILD = build_pb2.Build(
      builder=builder_common_pb2.BuilderID(
          project='chromeos',
          bucket='postsubmit',
          builder='snapshot-orchestrator',
      ),
  )

  yield api.test(
      'cache unpublished greenness',
      api.cros_infra_config.override_builder_configs_test_data(configs),
      api.properties(
          **{
              '$chromeos/auto_retry_util':
                  AutoRetryUtilProperties(experimental_features=[
                      ExperimentalFeature(
                          name=EXPERIMENTAL_FEATURE_WAITS_FOR_GREEN)
                  ])
          }),
      # Search for snapshot abc returns no greenness data.
      api.buildbucket.simulated_search_results(
          [
              GREENNESS_MISSING_SNAPSHOT_BUILD,
          ],
          'analyzing build results.get now green builders.get tot failure builders.buildbucket.search',
      ),
      # Don't search for snapshot abc again, even though it wasn't found the first time.
      api.post_process(
          post_process.DoesNotRun,
          'analyzing build results (2).get now green builders.get tot failure builders.buildbucket.search',
      ),
      api.post_process(post_process.DropExpectation),
  )
