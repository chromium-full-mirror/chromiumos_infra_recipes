# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from typing import List

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2

from recipe_engine import recipe_api


class AutoRetryUtilApi(recipe_api.RecipeApi):
  """A module for util functions associated with the CQ auto retries."""

  def initialize(self):
    self._cq_orch_default_child_buiders = [
        c.name for c in self.m.cros_infra_config.get_builder_config(
            'cq-orchestrator').orchestrator.child_specs
    ]

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
