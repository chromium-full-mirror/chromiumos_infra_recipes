# -*- coding: utf-8 -*-

# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for failures util functions."""
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from recipe_engine import recipe_api

from PB.go.chromium.org.luci.buildbucket.proto import common as bb_common_pb2


@dataclass
class Failure:
  """A failure in recipe execution.

  Fields:
    kind: Describes the kind of failure, e.g. 'build'
    title: Full title of the failure.
    link_map: title to URL map for the failed task.
    fatal: Whether or not the failure is fatal. Fatal failures cause
        recipes to fail when the failure is aggregated.
    id: a unique, reproducible name for this failure. For build-type
        failures, this is the builder name. For test-type failures this is the
        display_name.
    type: Type of the failure.
    failure_reason: The reason for the failure.
  """
  kind: str
  title: str
  link_map: Dict[str, str]
  fatal: bool
  id: str
  type: bb_common_pb2.Status = bb_common_pb2.FAILURE
  failure_reason: Optional[str] = None


class FailuresUtilApi(recipe_api.RecipeApi):
  """A module for util functions associated with failures printing & processing."""

  @dataclass
  class Results():
    """A class for keeping aggregated results from executions."""

    failures: List[Failure] = field(default_factory=List)
    successes: Dict[str, int] = field(default_factory=Dict)

    def add_failures(self, failures: List[Failure]) -> None:
      """Append failures to the list.

      Args:
        failures (List[Failure]): A List of Failure objects to
          append.
      """
      if failures:
        self.failures += failures

    def add_successes(self, successes: Dict[str, int]) -> None:
      """Update the successes numbers.

      Args:
        successes (Dict[str, int]): A Dict of success count per test kind to be
          updated with.
      """
      if successes:
        self.successes = {
            i: self.successes.get(i, 0) + successes.get(i, 0)
            for i in set(self.successes).union(successes)
        }

    def add_results(self, results) -> None:
      """Update the results.

      Args:
        results (Results): an object containing the list[Failure] of all
          failures discovered in the given runs and a Dict mapping a task kind
          with the number of successes.
      """
      self.add_failures(results.failures)
      self.add_successes(results.successes)

  def _proto_to_step_status(self, proto_status: bb_common_pb2.Status):
    """Convert from bb_common_pb2.Status to api.step status.

    Args:
      status: The status of the step.

    Returns:
      str representing status as listed in step/api.py.
    """
    if proto_status == bb_common_pb2.SUCCESS:
      return self.m.step.SUCCESS
    if proto_status == bb_common_pb2.INFRA_FAILURE:
      return self.m.step.EXCEPTION
    return self.m.step.FAILURE

  def present_run(self, title, link_map, status, critical=True):
    with self.m.step.nest(title) as presentation:
      if status != bb_common_pb2.SUCCESS and not critical:
        presentation.step_text = 'failed but is not critical'
        presentation.status = self.m.step.SUCCESS
      else:
        presentation.status = self._proto_to_step_status(status)
      for link_text, link_url in link_map.items():
        presentation.links[link_text] = link_url
      return
