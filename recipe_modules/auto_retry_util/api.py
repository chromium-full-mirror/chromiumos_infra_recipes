# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from typing import List, Tuple

from google.protobuf import json_format, timestamp_pb2

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import (builder_common as
                                                       builder_common_pb2)
from PB.go.chromium.org.luci.buildbucket.proto import (builds_service as
                                                       builds_service_pb2)
from PB.go.chromium.org.luci.buildbucket.proto import common as bb_common_pb2

from recipe_engine import recipe_api

# Start looking back at 1 days worth of data while we are still developing.
DEFAULT_LOOKBACK_WINDOW = 60 * 60 * 24 * 1

RETRYABLE_STATUSES = [
    bb_common_pb2.FAILURE,
    bb_common_pb2.INFRA_FAILURE,
]


class AutoRetryUtilApi(recipe_api.RecipeApi):
  """A module for util functions associated with the CQ auto retries."""

  def initialize(self):
    self._cq_orch_default_child_buiders = [
        c.name for c in self.m.cros_infra_config.get_builder_config(
            'cq-orchestrator').orchestrator.child_specs
    ]

  def _get_child_builders(
      self, cq_run: build_pb2.Build) -> Tuple[List[str], List[str]]:
    """Returns the names of the child builders for the given cq-orchestrator.

    Args:
      cq_run: The cq-orchestrator build for which to get the child builders.

    Returns:
      successful_builders, unsuccessful_builders: A tuple of the names of the
          child builders categorized by whether they passed or not.
    """
    successful_builders = []
    unsuccessful_builders = []
    output_dict = json_format.MessageToDict(cq_run.output.properties)
    child_build_info = output_dict.get('child_build_info', [])

    for b in child_build_info:
      relevant = b.get('relevant', False)
      builder_name = b.get('builder', {}).get('builder')
      status = b.get('status')

      if not relevant:
        continue
      if status == 'SUCCESS':
        successful_builders.append(builder_name)
      else:
        unsuccessful_builders.append(builder_name)

    return successful_builders, unsuccessful_builders

  def analyze_build_failures(
      self, cq_run: build_pb2.Build) -> Tuple[List[str], List[str], List[str]]:
    with self.m.step.nest('analyzing %d' % cq_run.id) as pres:
      retryable_failure_builders = []
      outstanding_failure_builders = []

      successful_builders, unsuccessful_builders = self._get_child_builders(
          cq_run)

      # Builders which failed but are not longer CQ blockers are now retryable.
      active_cq_verifiers = self._submission_blocking_builders(cq_run)
      removed_verifier_failure_builders = [
          b for b in unsuccessful_builders if b not in active_cq_verifiers
      ]
      retryable_failure_builders.extend(removed_verifier_failure_builders)
      outstanding_failure_builders = [
          b for b in unsuccessful_builders
          if b not in retryable_failure_builders
      ]

      pres.links[str(
          cq_run.id)] = self.m.buildbucket.build_url(build_id=cq_run.id)
      pres.step_text = '%d success, %d retryable, %d outstanding' % (
          len(successful_builders), len(retryable_failure_builders),
          len(outstanding_failure_builders))
      pres.logs['successful_builders'] = sorted(successful_builders)
      pres.logs['retryable_failure_builders'] = sorted(
          retryable_failure_builders)
      pres.logs['outstanding_failure_builders'] = sorted(
          outstanding_failure_builders)

    return (successful_builders, retryable_failure_builders,
            outstanding_failure_builders)

  def _submission_blocking_builders(self, cq_run: build_pb2.Build) -> List[str]:
    """Returns the names of builders which block submission for this CQ run.

    A blocking builder is a builder which must pass in order for the CQ run to
    succeed.

    Currently, blocking builders are defined as all the builders in the
    cq-orchestrator's child specs in addition to all builders which were
    explicitly forced relevant via CL footers.

    This does not currently take into account RUN_WHEN rules.

    Args:
      cq_run: The CQ run for which to get blocking builders.
    """
    forced_relevant_builders = []
    if 'found_force_relevant_targets' in cq_run.output.properties:
      forced_relevant_builders = list(
          cq_run.output.properties['found_force_relevant_targets'])
    return self._cq_orch_default_child_buiders + forced_relevant_builders

  def _get_current_cq_orchs_with_retryable_statuses(
      self) -> List[build_pb2.Build]:
    """Returns cq-orchestrators that are "current" and have a retryable status.

    "Current" means that the cq-orchestrator was the most recent cq-orchestrator
    run for that cq_cl_group.
    """

    with self.m.step.nest('query for cq-orchestrators') as pres:
      builder = builder_common_pb2.BuilderID(builder='cq-orchestrator',
                                             bucket='cq', project='chromeos')
      create_time = bb_common_pb2.TimeRange(
          start_time=timestamp_pb2.Timestamp(
              seconds=int(self.m.buildbucket.build.start_time.seconds) -
              DEFAULT_LOOKBACK_WINDOW))
      search_predicate = builds_service_pb2.BuildPredicate(
          builder=builder, create_time=create_time)

      # The builds are returned ordered from newest-to-oldest.
      fields = self.m.buildbucket.DEFAULT_FIELDS | {'tags'}
      cq_orch_runs = self.m.buildbucket.search(search_predicate, fields=fields)
      cq_orch_runs = sorted(cq_orch_runs,
                            key=lambda build: build.create_time.seconds,
                            reverse=True)

      # Get the latest cq-orchestrator run for each cq_cl_group.
      cl_group_to_run_mapping = {}
      for x in cq_orch_runs:
        cq_cl_group = self.m.cros_tags.get_single_value('cq_cl_group_key',
                                                        x.tags)
        if cq_cl_group not in cl_group_to_run_mapping:
          cl_group_to_run_mapping[cq_cl_group] = x

      # Only return the builds with a retryable status.
      builds = [
          x for x in cl_group_to_run_mapping.values()
          if x.status in RETRYABLE_STATUSES
      ]
      pres.step_text = 'found %d builds' % len(builds)
      for b in builds:
        pres.links[b.id] = self.m.buildbucket.build_url(build_id=b.id)
      return builds

  def cq_retry_candidates(self) -> List[build_pb2.Build]:
    """Returns cq-orchestrator builds which may be elegible for auto retry.

    # TODO(b/291767456): Expand to include all criteria listed in the bug.
    Candidate cq-orchestrator builds must meet the following criteria:
      * The build status is in RETRYABLE_STATUSES.
      * The build is the latest cq attempt for the CLs under test.
    """
    return self._get_current_cq_orchs_with_retryable_statuses()
