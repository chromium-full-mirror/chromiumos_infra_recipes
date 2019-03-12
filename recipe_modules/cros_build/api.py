# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from collections import defaultdict

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

from recipe_engine import recipe_api


class CompositeBuildFailure(recipe_api.StepFailure):

  def __init__(self, name_or_reason, builds, result=None):
    self.builds = builds
    super(CompositeBuildFailure, self).__init__(name_or_reason, result=result)

  def reason_message(self):
    return ("%s: {}" % self.name).format("\n".join(
        [str(build.id) for build in self.builds]))  # pragma: no cover

  def __str__(self):  # pragma: nocover
    return "One or more Step Failures in %s" % self.name


class CrosBuildApi(recipe_api.RecipeApi):
  """High level build steps to be called from orchestrator / e2e tests."""

  @recipe_api.composite_step
  def schedule_child_builders(self, name, builder, build_config):
    """Schedule buildbucket builds for all child builders.

    Args:
      * name (str): Step name.
      * builder (str): Name of builder.
      * build_config (list[dict]): Build config to schedule.

    Returns:
      list[build_pb2.Build]
    """
    requests = []
    for conf in build_config:
      request = self.m.buildbucket.schedule_request(
          builder='%s-%s' % (builder, conf['build_target']), properties=dict(
              reference_design=conf.get('reference_design', None),
              build_target=dict(name=conf['build_target']),
          ))
      requests.append(request)

    return self.m.buildbucket.schedule(requests, step_name=name)

  @recipe_api.composite_step
  def collect(self, scheduled_builds, step_name='collect'):
    """Wait for builds to complete, and return results.

    Args:
      * scheduled_builds (list[build_pb2.Build]): List of builds,
          as returned from schedule step.
      * step_name (str): Optional name of step.

    Returns:
      generator[build_pb2.Build]
    """
    # This function is structured to return a generator so that
    # we can later swap out buildbucket.collect_builds for
    # something that can return builds as they occur.
    build_ids = [build.id for build in scheduled_builds]
    completed_res = self.m.buildbucket.collect_builds(build_ids,
                                                      step_name=step_name)
    if not self._is_ok(completed_res):
      # We're in a deferred context if we get to this point,
      # so the error has already been captured by the aggregator.
      return

    completed_builds = self._get_result(completed_res)
    for build in completed_builds.values():
      yield build

  @recipe_api.composite_step
  def verify_builds(self, builds):
    """Verify all builds completed successfully.

    Args:
      * builds (list[build_pb2.Build]): List of completed builds.

    Raises:
      CompositeBuildFailure containing all failed builds.
    """
    # TODO(yshaul): ignore builders marked non-critical
    failed_builds = [
        build for build in builds if build.status != common_pb2.SUCCESS
    ]

    if failed_builds:
      raise CompositeBuildFailure('One or more child builders failed',
                                  failed_builds)

  @recipe_api.composite_step
  def download_build_report(self, build):
    """Download builds reports from isolate.

    Builders should set the 'build_report_hash' output property to
    point to the isolate hash of the build report. We then download
    the report from swarming and pass it into the test planner.

    Args:
      * build (build_pb2.Build): Completed build returned from the collect step.

    Returns:
      * Path of build report.
    """
    isolated_hash = build.output.properties['build_report_hash']
    download_path = self.m.path['cleanup'].join('build_reports', isolated_hash)

    # isolates.download correctly throws, even in deferred context.
    # no need to check is_ok from result.
    self.m.isolated.download('download.%s' % build.builder.builder,
                             isolated_hash, download_path)

    return download_path.join('build_report.json')

  @recipe_api.non_step
  def _get_result(self, step_output):
    # Get step result for both deferred and non-deferred contexts
    if isinstance(step_output, recipe_api.DeferredResult):
      return step_output.get_result()

    return step_output

  @recipe_api.non_step
  def _is_ok(self, step_output):
    # Get ok result for both deferred and non-deferred contexts
    if isinstance(step_output, recipe_api.DeferredResult):
      return step_output.is_ok

    # We're not in a deferred context, so we're good.
    return True
