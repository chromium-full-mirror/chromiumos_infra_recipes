# -*- coding: utf-8 -*-

# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.build_plan.examples.cq_build_plan import (
    CqBuildPlanProperties)

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/cq',
    'recipe_engine/properties',
    'looks_for_green',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

PROPERTIES = CqBuildPlanProperties


def RunSteps(api, properties):
  snapshot_ids = set(properties.snapshot_ids)
  unfinished, failed = api.looks_for_green.get_unfinished_or_failed_snapshot_ids(
      snapshot_ids)
  api.assertions.assertCountEqual(properties.expected_failed_snapshots, failed)
  api.assertions.assertEqual(
      sorted(properties.expected_failed_snapshots), sorted([x for x in failed]))

  api.assertions.assertCountEqual(properties.expected_unfinished_snapshots,
                                  unfinished)
  api.assertions.assertEqual(
      sorted(properties.expected_unfinished_snapshots),
      sorted([x for x in unfinished]))


def GenTests(api):

  def cq_orchestrator_build_with_gerrit_change(**kwargs):
    """Generate a test build proto with no gitiles commit project."""
    kwargs.setdefault('bucket', 'cq')
    kwargs.setdefault('builder', 'cq-orchestrator')
    return api.buildbucket.try_build(project='chromeos', **kwargs)

  success_builds = [
      build_pb2.Build(
          id=234, critical=common_pb2.YES, status=common_pb2.SUCCESS,
          builder={'builder': 'fake-snapshot'},
          tags=api.m.buildbucket.tags(snapshot='success-snapshot-0')),
      build_pb2.Build(
          id=234, critical=common_pb2.YES, status=common_pb2.ENDED_MASK,
          builder={'builder': 'fake-brask-snapshot'},
          tags=api.m.buildbucket.tags(snapshot='success-snapshot-1')),
      build_pb2.Build(
          id=234, critical=common_pb2.YES, status=common_pb2.SUCCESS,
          builder={'builder': 'fake-atlas-snapshot'},
          tags=api.m.buildbucket.tags(snapshot='success-snapshot-2')),
      build_pb2.Build(
          id=234, critical=common_pb2.YES, status=common_pb2.SUCCESS,
          builder={'builder': 'fake-coral-kernelnext-snapshot'},
          tags=api.m.buildbucket.tags(snapshot='success-snapshot-3')),
  ]
  yield api.test(
      'cq-looks-success',
      api.cq(run_mode=api.cq.FULL_RUN),
      cq_orchestrator_build_with_gerrit_change(
          experiments=['chromeos.cros_infra_config.cq_looks']),
      api.properties(
          snapshot_ids=[build.tags[0].value for build in success_builds],
          expected_failed_snapshots=[],
          expected_unfinished_snapshots=[],
      ),
      api.buildbucket.simulated_search_results(
          builds=success_builds,
          step_name='unfinished or failed snapshots.buildbucket.search'),
  )

  mixed_builds = [
      build_pb2.Build(id=123, critical=common_pb2.YES,
                      status=common_pb2.FAILURE,
                      builder={'builder': 'fake-drallion-snapshot'},
                      tags=api.buildbucket.tags(snapshot='failed-snapshot-0')),
      build_pb2.Build(
          id=123, critical=common_pb2.YES, status=common_pb2.INFRA_FAILURE,
          builder={'builder': 'fake-zork-snapshot'},
          tags=api.m.buildbucket.tags(snapshot='failed-snapshot-1')),
      build_pb2.Build(
          id=123, critical=common_pb2.YES, status=common_pb2.SCHEDULED,
          builder={'builder': 'fake-hana-snapshot'},
          tags=api.buildbucket.tags(snapshot='unfinished-snapshot-0')),
      build_pb2.Build(
          id=123, critical=common_pb2.YES, status=common_pb2.STATUS_UNSPECIFIED,
          builder={'builder': 'fake-hatch-arc-r-snapshot'},
          tags=api.buildbucket.tags(snapshot='unfinished-snapshot-1')),
      build_pb2.Build(
          id=123, critical=common_pb2.YES, status=common_pb2.STARTED,
          builder={'builder': 'fake-fizz-snapshot'},
          tags=api.buildbucket.tags(snapshot='unfinished-snapshot-2')),
      build_pb2.Build(
          id=123, critical=common_pb2.YES, status=common_pb2.CANCELED,
          builder={'builder': 'fake-bubs-snapshot'},
          tags=api.buildbucket.tags(snapshot='unfinished-snapshot-3')),
      build_pb2.Build(id=123, critical=common_pb2.YES,
                      status=common_pb2.SUCCESS,
                      builder={'builder': 'fake-zork-floss-snapshot'},
                      tags=api.buildbucket.tags(snapshot='success-snapshot-0')),
      build_pb2.Build(
          id=123, critical=common_pb2.YES, status=common_pb2.CANCELED,
          builder={'builder': 'fake-brask-snapshot'},
          tags=api.buildbucket.tags(snapshot='unfinished-snapshot-3')),
      build_pb2.Build(
          id=123, critical=common_pb2.NO, status=common_pb2.SUCCESS,
          builder={'builder': 'fake-noncrit-snapshot'},
          tags=api.buildbucket.tags(snapshot='unfinished-snapshot-4')),
      build_pb2.Build(
          id=123, critical=common_pb2.YES, status=common_pb2.SUCCESS,
          builder={'builder': 'fake-bubs-postsubmit'},
          tags=api.buildbucket.tags(snapshot='unfinished-snapshot-5')),
  ]

  yield api.test(
      'cq-looks-failed-unfinished-success-snapshot',
      api.cq(run_mode=api.cq.FULL_RUN),
      cq_orchestrator_build_with_gerrit_change(
          experiments=['chromeos.cros_infra_config.cq_looks']),
      api.properties(
          snapshot_ids=[build.tags[0].value for build in mixed_builds],
          expected_failed_snapshots=[
              'failed-snapshot-0',
              'failed-snapshot-1',
          ],
          expected_unfinished_snapshots=[
              'unfinished-snapshot-0',
              'unfinished-snapshot-1',
              'unfinished-snapshot-2',
              'unfinished-snapshot-3',
              'unfinished-snapshot-4',
              'unfinished-snapshot-5',
          ],
      ),
      api.buildbucket.simulated_search_results(
          builds=mixed_builds,
          step_name='unfinished or failed snapshots.buildbucket.search'),
  )
