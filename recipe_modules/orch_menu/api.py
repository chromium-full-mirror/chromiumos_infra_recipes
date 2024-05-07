# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API providing a menu for orchestrator steps"""

from __future__ import division

import contextlib
from collections import defaultdict
from collections import namedtuple
from typing import Any, Dict, List, Optional, Tuple

from google.protobuf import json_format

from PB.chromiumos.build.api.container_metadata import ContainerMetadata
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.checkpoint import RetryStep
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import (builds_service as
                                                       builds_service_pb2)
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_engine import result as result_pb2
from PB.recipe_modules.chromeos.chrome.chrome import ChromeProperties
from PB.recipe_modules.chromeos.cros_source.cros_source import ManifestLocation
from recipe_engine.engine_types import StepPresentation
from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure

CHILD_BUILD_SEARCH_FIELDS = frozenset({
    'id', 'create_time', 'start_time', 'end_time', 'status', 'builder.bucket',
    'builder.builder', 'output.properties'
})

_manifest_info = namedtuple('_manifest_info',
                            ['name', 'gitiles_commit', 'path', 'url'])


class BuildsStatus():
  """The running status of the builds.

  Properties:
    completed_builds (list[Build]): The completed builds.
    testable_builds (list[Build]): The list of testable builds.
    failures (list[Failure]): The list of failures.
    fatal_failures (list[Failure]): The list of fatal failures.
    running_builds (list[Build]): The still-running builds (to be collected
        after HW test.)
  """

  def __init__(self, completed, failures, configs, running=None):
    """

    Args:
      completed (list[Build]): The builds.
      failures (list[Failure]): The failures
      configs (dict{name: BuilderConfig}): Builder config dictionary.
      running (list[Build]): The running builds, or None.
    """
    self.completed_builds = completed
    self.failures = failures
    self._configs = configs
    self.running_builds = running or []

  @property
  def testable_builds(self):
    return [b for b in self.completed_builds if self._is_testable(b)]

  @property
  def fatal_failures(self):
    return [f for f in self.failures if f.fatal]

  def update(self, completed=None, failures=None, configs=None, running=None):
    """Update the status.

    Add the new builds and failures to our attributes.  Remove completed builds
    from running list.

    Args:
      completed (list[Build]): The builds.
      failures (list[Failure]): The failures
      configs (dict{name: BuilderConfig}): Builder config dictionary.
      running (list[Build]): The still-running builds, or None.
    """
    self._configs = configs or self._configs
    self._update_failures(failures or [])
    new_completed_builds = [
        b for b in completed or [] if b not in self.completed_builds
    ]
    self.completed_builds += new_completed_builds
    # Remove any just completed builds from self.running_builds.
    completed_ids = set(b.id for b in self.completed_builds)
    self.running_builds = [
        b for b in self.running_builds if b.id not in completed_ids
    ]
    # Add any new running builds to self.running_builds.
    running_ids = set(b.id for b in self.running_builds)
    self.running_builds += [b for b in running or [] if not b.id in running_ids]

  def _update_failures(self, failure_updates):
    """Update self._failures with the list of failure_updates.

    If a failure is new, add it to self._failures. If the a failure is for an id
    which already exists in self._failures, the updated failure overrides the
    existing failure.

    Args:
      failure_updates (list[Failure]): Failures with which to update build_status.
    """
    failure_update_ids = [f.id for f in failure_updates]
    unchanged_failures = [
        f for f in self.failures if f.id not in failure_update_ids
    ]
    self.failures = failure_updates + unchanged_failures

  def _is_testable(self, build):
    """Whether the build is testable."""
    return (build.status == common_pb2.SUCCESS and
            self._configs.get(build.builder.builder))


class OrchMenuApi(recipe_api.RecipeApi):
  """A module with steps used by orchestrators.

  Orchestrators do not call other recipe modules directly: they always get there
  via this module, and are a simple sequence of steps.
  """

  def __init__(self, properties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._external_gitiles_commit = None
    # Our properties: OrchMenuProperties ($chromeos/orch_menu).
    self._properties = properties
    self._builds_status = BuildsStatus([], [], {})
    self._is_cq_orchestrator = False
    self._is_release_orchestrator = False
    self._is_factory_orchestrator = False
    self._is_public_orchestrator = False
    self._relevant_child_builder_names = []

    self._builder_to_collect_value = defaultdict(
        lambda: BuilderConfig.Orchestrator.ChildSpec.CollectHandling.Name(
            BuilderConfig.Orchestrator.ChildSpec.COLLECT_HANDLING_UNSPECIFIED))

  def initialize(self):
    # Set the default buildbucket host for buildbucket calls.
    self.m.buildbucket.host = self.m.buildbucket.HOST_PROD

  @property
  def config(self):
    return self.m.cros_infra_config.config

  @property
  def gitiles_commit(self):
    return self.m.cros_infra_config.gitiles_commit

  @property
  def external_gitiles_commit(self):
    return self._external_gitiles_commit

  @property
  def gerrit_changes(self):
    return self.m.cros_infra_config.gerrit_changes

  @property
  def is_dry_run(self):
    return self.m.cv.active and self.m.cv.run_mode == self.m.cv.DRY_RUN

  @property
  def builds_status(self):
    return self._builds_status

  @property
  def is_cq_orchestrator(self):
    return self._is_cq_orchestrator

  @property
  def is_release_orchestrator(self):
    return self._is_release_orchestrator

  @property
  def is_factory_orchestrator(self):
    return self._is_factory_orchestrator

  @property
  def is_public_orchestrator(self):
    return self._is_public_orchestrator

  @property
  def is_postsubmit_orchestrator(self):
    return self.m.buildbucket.build.builder.builder.endswith(
        'postsubmit-orchestrator')

  @property
  def is_snapshot_orchestrator(self):
    return self.m.buildbucket.build.builder.builder.endswith(
        'snapshot-orchestrator')

  @property
  def chromium_src_ref_cl_tag(self):
    return self.m.cros_tags.cq_cl_tag_value('chromium_src_ref',
                                            self.m.buildbucket.build.tags)

  @property
  def skip_paygen(self):
    return self._properties.skip_paygen

  @property
  def relevant_child_builder_names(self):
    return self._relevant_child_builder_names

  @property
  def chrome_module_child_props(self):
    return json_format.MessageToDict(
        ChromeProperties(version=self.chromium_src_ref_cl_tag))

  @contextlib.contextmanager
  def setup_orchestrator(self):
    """Initial setup steps for the orchestrator.

    This context manager returns with all of the contexts that the orchestrator
    needs to have when it runs, for cleanup to happen properly.

    If appropriate, any inflight orchestrator has finished before we return.

    Raises:
      StepFailure if no config is found.

    Returns:
      BuilderConfig or None, with an active context.
    """
    with self.m.bot_cost.build_cost_context(), \
        self.m.cros_source.checkout_overlays_context():
      with self.m.step.nest('set up orchestrator') as presentation:
        config = self.m.cros_source.configure_builder(
            self.m.buildbucket.gitiles_commit,
            self.m.buildbucket.build.input.gerrit_changes)

        presentation.links['manifest snapshot revision'] = (
            self.m.gitiles.file_url(self.gitiles_commit, 'snapshot.xml'))

        use_external = self.gitiles_commit.project == 'chromiumos/manifest'
        external_commit = self.m.cros_source.checkout_manifests(
            is_staging=self.m.cros_infra_config.is_staging,
            checkout_internal=not use_external, checkout_external=use_external)
        self._external_gitiles_commit = external_commit

        is_staging = self.m.cros_infra_config.is_staging

        if config and config.id.type == BuilderConfig.Id.CQ:
          self._is_cq_orchestrator = True

        # If release orchestrator, full checkout and pin manifest.
        if config and config.id.type == BuilderConfig.Id.RELEASE:
          self._is_release_orchestrator = True
          self._create_buildspec()

        if config and config.id.type == BuilderConfig.Id.FACTORY:
          self._is_factory_orchestrator = True
          with self.m.workspace_util.sync_to_commit(staging=is_staging):
            bump_version = self._properties.bump_version and not is_staging
            self.m.cros_version.bump_version(dry_run=not bump_version)
            self.m.cros_release.create_buildspec(
                dry_run=is_staging,
                gs_location=self._properties.buildspec_gs_path)

        if config and config.id.type == BuilderConfig.Id.PUBLIC:
          self._is_public_orchestrator = True
          # Need to sync to buildspec in the public orchestrator so that
          # chromeos_version.sh accurately reflects the version.
          # b/238330273 for context.
          with self.m.workspace_util.sync_to_commit(staging=is_staging):
            pass

      if config:
        if self.gerrit_changes:
          # Limit to staging and cq-orchestrator for now. We'll want to ask
          # the RBS team how tryjobs could be affected.
          if is_staging and self._is_cq_orchestrator:
            with self.m.context(cwd=self.m.cros_source.workspace_path):
              self.m.cros_source.sync_checkout(self.gitiles_commit)
              # This step will throw a StepFailure if changes cannot be applied
              # to chosen snapshot.
              self.m.workspace_util.apply_changes()
          elif not self.m.gerrit.changes_submittable(self.gerrit_changes):
            raise recipe_api.StepFailure(
                'Merge conflict detected! Please rebase and retry.')

      # If we are waiting on inflight orchestrators, do that now.
      self._wait_for_inflight_orchestrator()

      # Yield while inside of the bot_cost.build_cost_context.
      yield config

  def _create_buildspec(self):
    """Create a release buildspec."""
    with self.m.checkpoint.retry(RetryStep.CREATE_BUILDSPEC) as run_step:
      if run_step:
        with self.m.workspace_util.sync_to_commit(
            staging=self.m.cros_infra_config.is_staging):
          # If we're syncing to a specific manifest, don't bump the version.
          if not self.m.cros_source.sync_to_manifest:
            # If we're not on ToT, we need to uprev packages since we don't
            # have annealing.
            if not self.m.cros_source.is_tot:
              if not self.m.cros_release.uprev_packages():
                raise StepFailure('Failed to uprev all changes')

            bump_version = self._properties.bump_version and not self.m.cros_infra_config.is_staging
            # Release orchestrators may build for a pinned manifest that is
            # behind tip-of-branch and need to create a version bump CL
            # using a local diff to ensure other files are not included.
            use_local_diff = self.is_release_orchestrator
            self.m.cros_version.bump_version(dry_run=not bump_version,
                                             use_local_diff=use_local_diff)

            self.m.cros_release.create_buildspec(
                dry_run=self.m.cros_infra_config.is_staging,
                gs_location=self._properties.buildspec_gs_path)
          if self._properties.schedule_public_build:
            with self.m.checkpoint.retry(
                RetryStep.PUBLIC_BUILD_LKGM) as run_step:
              if run_step:
                self.m.cros_lkgm.schedule_public_build()
      else:
        self.m.cros_release.buildspec = ManifestLocation(
            manifest_gs_path=self.m.checkpoint.buildspec_gs_uri)

  def create_cq_orch_recipe_result(self) -> result_pb2.RawResult:
    """Create the correct return value for RunSteps."""
    # If there are any remaining children to collect, collect them now.
    self._collect_remaining_children(no_nest=True)

    with self.m.step.nest('clean up orchestrator'):
      # Recheck the BuilderConfigs at HEAD, one last time, to see if any
      # failed builders are now noncritical.
      self._non_critical_build_check('final build criticality update',
                                     self.builds_status.completed_builds,
                                     self.builds_status.failures)
      # Set child output ids if any
      self.add_child_info_to_output_property()

      # TODO(b/316010599): Remove after the experiment.
      with self.m.failures.ignore_exceptions():
        if self.m.build_plan.cros_query_relevant_builder_configs is not None:

          # All the builders that were scheduled and collected. Non-critical
          # builds do not get collected.
          collected_builders = {
              x.builder.builder for x in self.builds_status.completed_builds
          }
          cros_query_relevant_builders = {
              b.id.name
              for b in self.m.build_plan.cros_query_relevant_builder_configs
          }
          portage_relevant_child_builders = set(
              self._relevant_child_builder_names)

          # CrOS query relevant, but not Portage relevant.
          cros_query_false_positives = (
              cros_query_relevant_builders - portage_relevant_child_builders)
          # Portage relevant, not CrOS query relevant.
          cros_query_false_negatives = (
              portage_relevant_child_builders - cros_query_relevant_builders)
          # Correctly predicated non-relevant builders. Not relevant by both
          # CrOS query and Portage. This is the impact of CrOS query.
          correctly_predicted_not_relevant = {
              x for x in collected_builders
              if x not in cros_query_relevant_builders and
              x not in portage_relevant_child_builders
          }

          self.m.easy.set_properties_step(
              cros_query_response_was_identical=cros_query_relevant_builders ==
              portage_relevant_child_builders,
              collected_builders=sorted(collected_builders),
              cros_query_relevant_builders=sorted(cros_query_relevant_builders),
              portage_relevant_builders=sorted(portage_relevant_child_builders),
              cros_query_false_positives=sorted(cros_query_false_positives),
              cros_query_false_negatives=sorted(cros_query_false_negatives),
              cros_query_correctly_predicted_not_relevant=sorted(
                  correctly_predicted_not_relevant))

    successes = {
        'build':
            self._count_successful_critical_relevant_cq_builds(
                self.builds_status.completed_builds)
    }

    results = self.m.failures.Results(failures=self.builds_status.failures,
                                      successes=successes)

    # Output whether any of the cq-orchestrator children (build and test) had
    # fatal failures. This is currently used by cq-auto-retrier.
    has_child_failures = any(failure.fatal for failure in results.failures)
    self.m.easy.set_properties_step(has_child_failures=has_child_failures)

    return self.m.failures.aggregate_failures(results)

  def create_recipe_result(
      self, include_build_details: bool = False,
      ignore_build_test_failures: bool = False) -> result_pb2.RawResult:
    """Create the correct return value for RunSteps.

    Args:
      include_build_details: If True augment RawResults.summary_markdown
        with additional details about the build for both successes and failures.
      ignore_build_test_failures: If True, we will still produce a summary
        of failures if present, but we will not set the build status to FAILURE.

    Returns:
      (recipe_engine.result_pb2.RawResult) The return value for RunSteps.
    """
    # If there are any remaining children to collect, collect them now.
    self._collect_remaining_children()

    with self.m.step.nest('clean up orchestrator'):
      # Recheck the BuilderConfigs at HEAD, one last time, to see if any
      # failed builders are now noncritical.
      self._non_critical_build_check('final build criticality update',
                                     self.builds_status.completed_builds,
                                     self.builds_status.failures)
      self.m.greenness.print_step()
      # Set child output ids if any
      self.add_child_info_to_output_property()

    successes = {
        'build':
            self._count_successful_critical_builds(
                self.builds_status.completed_builds)
    }

    results = self.m.failures.Results(failures=self.builds_status.failures,
                                      successes=successes)

    raw_result = self.m.failures.aggregate_failures(results,
                                                    ignore_build_test_failures)
    if include_build_details:
      summary_markdown = 'Full version: {}'.format(
          self.m.cros_version.version.legacy_version)
      if raw_result.summary_markdown:
        summary_markdown += '\n\n{}'.format(raw_result.summary_markdown)
      raw_result = result_pb2.RawResult(status=raw_result.status,
                                        summary_markdown=summary_markdown)
    return raw_result

  def _count_successful_critical_builds(self, builds):
    return len([
        b for b in builds
        if b.critical == common_pb2.YES and b.status == common_pb2.SUCCESS
    ])

  def _count_successful_critical_relevant_cq_builds(self, builds):
    return len([
        b for b in builds if b.critical == common_pb2.YES and
        b.status == common_pb2.SUCCESS and self.cq_relevant(b)
    ])

  def _non_critical_build_check(self, step_name, builds, failures):
    """Update failures based on the current criticality of the builders.

    Args:
      step_name (str): the name for the step.
      builds (list[Build]): Builds to review.
      failures (list[Failure]): Failures to review.
    """
    with self.m.step.nest(step_name) as presentation:
      self.m.cros_infra_config.force_reload()
      configs = self.m.cros_infra_config.safe_get_builder_configs(
          [b.builder.builder for b in builds])
      failures = self.m.failures.update_non_critical_build_failures(
          failures, configs, presentation)
      self.builds_status.update(failures=failures, configs=configs)

  def _wait_for_inflight_orchestrator(self):
    """If there is an inflight orchestrator, wait for it."""

    if not (self.gerrit_changes and self._properties.enable_history and
            self._properties.assert_singleton):
      # In order to join an inflight orchestrator, there must be changes and we
      # must have history, and only allow one orchestrator for a cl_group.  If
      # that is not the case, we're done.
      return

    with self.m.step.nest('find inflight orchestrator') as pres:
      my_build = self.m.buildbucket.build
      running_builds = self.m.cros_history.get_matching_builds(
          my_build, statuses=[common_pb2.STARTED])

      # Make sure we are not in the list.
      running_builds = [b for b in running_builds if b.id != my_build.id]

      # Is a run of the same configuration ongoing? If so, inform and join().
      if not running_builds:
        pres.step_text = 'found no inflight run'
        return

      pres.step_text = 'found {} inflight run(s) to wait on'.format(
          len(running_builds))

      # Give the UI the links to STARTED builds with same configuration.
      for build in running_builds:
        title = self.m.naming.get_build_title(build)
        url = self.m.buildbucket.build_url(build_id=build.id)
        pres.links[title] = url

      # Wait for all started builds.
      self.m.buildbucket.collect_builds(
          [b.id for b in running_builds],
          step_name='waiting for existing runs',
          timeout=60 * 60 * 23,
      )

  def _poll_for_output_prop(
      self,
      build_ids: List[int],
      output_property: str,
      timeout: int,
      interval: int = 60,
  ) -> Dict[int, build_pb2.Build]:
    """Poll until all of build_ids are completed or have set an output property.

    If timeout is reached, the set of currently completed builds will be
    returned.

    Args:
      build_ids: Ids of builds to poll.
      property: Name of the property to poll for. Note that the truthiness of
        the property will not be checked, just whether it is set.
      timeout: Maximum seconds to wait for builds to complete or set property.
      interval: Delay in seconds between requests for the state of the builds.

    Returns:
      A map from build id -> build_pb2.Build
    """
    if not build_ids:
      return {}

    # Call build_poller with '-json -' to print build protos to stdout. Build
    # protos will be printed as jsonproto, one per-line.
    try:
      poll_result = self.m.gobin.call(
          'build_poller',
          [
              'collect', '-loglevel', 'debug', '-outputprop', output_property,
              '-interval', f'{interval}s', '-json', '-'
          ] + build_ids,
          step_name='collect',
          timeout=timeout,
          stdout=self.m.raw_io.output_text(add_output_log=True),
          infra_step=True,
      )

      completed_builds = {}
      for line in poll_result.stdout.strip().split('\n'):
        build = build_pb2.Build()
        json_format.Parse(line, build, ignore_unknown_fields=True)
        completed_builds[build.id] = build
    except recipe_api.StepFailure as ex:
      # If build_poller timed out, return the current status of builds with
      # get_multi.
      if ex.had_timeout:
        completed_builds = self.m.buildbucket.get_multi(
            build_ids, fields=self.m.buildbucket.DEFAULT_FIELDS | {'tags'},
            step_name='collect after timeout')
      else:
        raise ex

    return completed_builds

  def plan_and_wait_for_images(
      self,
      run_step_name: Optional[str] = None,
      extra_child_props: Optional[Dict[str, Any]] = None,
  ) -> List[build_pb2.Build]:
    """Plan and schedule children, and wait until they have produced images.

    Args:
      run_step_name: Name for "run builds" step, or None.
      extra_child_props: If set, extra properties to append to the child
        builder requests.

    Returns:
      A list of builds that have produced images and are ready for testing.
    """
    with self.m.step.nest(run_step_name or 'run builds') as pres:
      child_specs = self._get_child_specs()
      collect_now, collect_after = self._filter_schedule_builds(
          pres, child_specs, extra_props=extra_child_props)

      # It is possible that some of the builds that uploaded testing artifacts
      # have completed after _poll_for_output_prop. However, we have not
      # explicitly collected them, so keep them in the running status; these
      # builds should be collected by later steps, e.g.
      # _collect_remaining_children.
      self._builds_status.update(running=collect_now + collect_after)

      # Wait until the children being used for end-to-end tests either complete
      # or upload testing artifacts.
      testable_builds = self._poll_for_output_prop(
          [b.id for b in collect_now], 'image_artifacts_uploaded',
          timeout=60 * 60 * 36).values()

      return list(testable_builds)

  def plan_and_run_children(self, run_step_name=None, results_step_name=None,
                            check_critical_step_name=None,
                            extra_child_props=None):
    """Plan, schedule, and run child builders.

    Args:
      run_step_name (str): Name for "run builds" step, or None.
      results_step_name (str): Name for "check build results" step, or None.
      check_critical_step_name (str): Name for "non-critical build check" step,
        or None.
      extra_child_props (dict): If set, extra properties to append to the child
        builder requests.
    Returns:
      (BuildsStatus): The current status of the builds.
    """
    with self.m.step.nest(run_step_name or 'run builds') as pres:
      completed_builds = None
      collect_after = None
      # This retry logic doesn't do anything with collect_after, and thus
      # only works with the release orchestrator.
      with self.m.checkpoint.retry(RetryStep.RUN_CHILDREN) as run_step:
        if run_step:
          collect_kwargs = {}
          collect_now, collect_after = [], []
          if self.m.checkpoint.is_run_step(RetryStep.RUN_FAILED_CHILDREN):
            # Conductor leverages `cros try retry` to retry builds.
            if not self.m.conductor.enabled or self.m.conductor.dryrun:
              raise StepFailure(
                  'RUN_FAILED_CHILDREN only works if conductor is enabled in non-dryrun mode.'
              )
            with self.m.step.nest(
                'only rerunning failed children') as presentation:
              presentation.logs['failed children'] = [
                  b.builder.builder
                  for b in self.m.checkpoint.failed_builder_children()
              ]
              # Don't naively schedule builds. Instead, use conductor to
              # retry failed builds from the previous run.
              collect_now = self.m.checkpoint.failed_builder_children()
              collect_kwargs['conductor_initial_retry'] = True
          else:
            # Schedule builds.
            collect_now, collect_after = self._filter_schedule_builds(
                pres, self._get_child_specs(), extra_props=extra_child_props)

          completed_builds = list(
              self._collect_builds([b.id for b in collect_now],
                                   collect_name='child builds',
                                   **collect_kwargs))
          self.add_child_info_to_output_property()
        else:
          results_step_name = '(RETRY-MODE) check build results from previous builds'
          completed_builds = self.m.buildbucket.get_multi(
              self.m.checkpoint.builder_children()).values()
          collect_after = []

    self._collect_and_check_build_results(
        completed_builds, results_step_name=results_step_name,
        check_critical_step_name=check_critical_step_name)
    successful_child_bbids = self.m.checkpoint.successful_builder_children_bbids(
    )
    if self.m.checkpoint.is_run_step(
        RetryStep.RUN_FAILED_CHILDREN) and successful_child_bbids:
      with self.m.step.nest('(RETRY-MODE) previously successful builds'):
        # Include the successful builds from the original build.
        previously_successful_builds = self.m.buildbucket.get_multi(
            successful_child_bbids).values()
        completed_builds += previously_successful_builds
        self._collect_and_check_build_results(
            previously_successful_builds,
            check_critical_step_name=check_critical_step_name)

    self._builds_status.update(running=collect_after)
    self.m.greenness.update_build_info(completed_builds)
    self.m.greenness.print_step()

    return self._builds_status

  def cq_relevant(self, build: build_pb2.Build) -> bool:
    """Whether the CQ child build was critical and relevant.

    Args:
      build: The child build.
    """
    # Assume relevant if the child doesn't have the relevant_build prop.
    return ('relevant_build' not in build.output.properties or
            build.output.properties['relevant_build'])

  def _collect_and_check_build_results(self, builds, results_step_name=None,
                                       check_critical_step_name=None):
    with self.m.step.nest(results_step_name or 'check build results') as pres:
      # Add the newly completed builds to build_status.
      self.builds_status.update(completed=builds)

      # Output information about child build relevancy.

      if self.config.id.type == BuilderConfig.Id.CQ:
        cq_relevant_builds = [
            x.builder.builder
            for x in self._builds_status.completed_builds
            if self.cq_relevant(x)
        ]
        pres.logs['cq_relevant_builds'] = sorted(cq_relevant_builds or
                                                 ['no relevant builds'])
        self._relevant_child_builder_names = cq_relevant_builds
        self.m.easy.set_properties_step(
            child_builds_relevant=len(cq_relevant_builds))

        # Rollup testing_toolchain: true if true from any child builds output
        cq_toolchain_outputs = [
            build.output.properties['testing_toolchain']
            for build in self._builds_status.completed_builds
            if 'testing_toolchain' in build.output.properties
        ]
        self.m.easy.set_properties_step(
            testing_toolchain=any(cq_toolchain_outputs))

      # Add the newly completed builds to build_status.
      failures = self.m.failures.get_build_results(
          builds, relevant_child_builder_names=self.relevant_child_builder_names
      ).failures
      self.builds_status.update(failures=failures)

    # Recheck the BuilderConfigs at HEAD to see if any failed builds are now
    # non-critical.
    self._non_critical_build_check(
        check_critical_step_name or 'non-critical build check', builds,
        failures)

  def _get_child_specs(self):
    """Get the list of child specs this builder should run.

    Returns:
      (list[BuilderConfig.Orchestrator.ChildSpec]) The list of child_specs.
    """
    return [
        BuilderConfig.Orchestrator.ChildSpec(
            name=cb,
            collect_handling=BuilderConfig.Orchestrator.ChildSpec.COLLECT)
        for cb in self._properties.child_builds
    ] or self.config.orchestrator.child_specs

  def _filter_schedule_builds(
      self,
      parent_step: StepPresentation,
      child_specs: List[BuilderConfig.Orchestrator.ChildSpec],
      extra_props: Optional[Dict[str, Any]] = None,
  ) -> Tuple[List[build_pb2.Build], List[build_pb2.Build]]:
    """Find the builds we need, filter those already started, and run.

    Most of the heavy lifting is done in get_build_plan.

    Args:
      parent_step (Step): the calling step, used for presentation purposes.
      child_specs (list(ChildSpec)): A list of child specs.
      extra_props (dict): Extra properties to append to child requests.
        Value can be a callback function to be executed when applying the props.

    Returns:
      (list[Build], list[Build]) Two lists of scheduled builds, the first
        contains builds that have either completed or have COLLECT handling, the
        second contains builds that have COLLECT_AFTER_HW_TEST handling.
    """
    completed_builds, new_build_requests = (
        self.m.build_plan.get_build_plan(
            child_specs=child_specs,
            enable_history=self._properties.enable_history,
            gerrit_changes=self.gerrit_changes,
            internal_snapshot=self.gitiles_commit,
            external_snapshot=self.external_gitiles_commit))
    parent_step.step_text = ('{} new, {} recycled'.format(
        len(new_build_requests), len(completed_builds)))

    log_msg = ''
    new_builds = []
    if new_build_requests:
      # Add in extra_props.
      if extra_props:
        # Evaluate extra props for values that are callback functions.
        # Not cache all values to be compatible with existing tests that
        # mock a dict (`.items()`).
        evaluated_extra_props_cache = {}
        for key, val in extra_props.items():
          if callable(val):
            evaluated_extra_props_cache[key] = val()
        for _, req in enumerate(new_build_requests):
          # Only set the value if it's not set already.
          # We don't want to clobber anything.
          for key, val in extra_props.items():
            if callable(val):
              # Use cached value to avoid redundant callback executions.
              val = evaluated_extra_props_cache[key]
            if key not in req.properties:
              req.properties[key] = val
            elif req.properties[key] != val:
              log_msg = 'extra_props mismatch: [{}] = {} but had extra_prop value {}'.format(
                  key, req.properties[key], val)

      # Implement sleepy builds for GoB smoothing: crbug.com/1063143
      with self.m.step.nest('schedule new builds') as presentation:
        if log_msg:
          presentation.step_text = log_msg

        # Spawn off the child builds in greenlets!
        with self.m.buildbucket.with_host(self.m.buildbucket.HOST_PROD):
          futures = []

          child_specs_dict = {cs.name: cs for cs in child_specs}

          # With .strftime('%w'), Sunday is 0 and Saturday is 6.
          today = int(self.m.time.utcnow().date().strftime('%w'))

          for new_build_request in new_build_requests:
            builder_name = new_build_request.builder.builder

            # If custom build cadence is enabled, schedule based on which
            # day of the week it is.
            if self._properties.custom_build_cadence:
              child_spec = child_specs_dict[builder_name]
              # If `run_on` is not set at all, default to daily cadence.
              if child_spec.run_on and today not in child_spec.run_on:
                step_text = (
                    f'{builder_name} configured to run on days '
                    f'{",".join([str(day) for day in child_spec.run_on])}, '
                    f'today is {today}')
                self.m.step.empty(builder_name, step_text=step_text)
                continue

            # Request new builds and add to total existing.
            futures.append(
                self.m.futures.spawn(self.m.buildbucket.schedule,
                                     [new_build_request],
                                     url_title_fn=self.m.naming.get_build_title,
                                     step_name=builder_name))
            if self._properties.stagger_children_seconds:
              self.m.time.sleep(self._properties.stagger_children_seconds)

          for f in self.m.futures.iwait(futures):
            new_builds += f.result()

    self.add_child_info_to_output_property()

    collect_when_dict = self.categorize_builds_by_collect_handling(
        child_specs, new_builds)

    return (completed_builds +
            collect_when_dict[BuilderConfig.Orchestrator.ChildSpec.COLLECT],
            collect_when_dict[
                BuilderConfig.Orchestrator.ChildSpec.COLLECT_AFTER_HW_TEST])

  def _collect_builds(self, build_ids, collect_name=None,
                      conductor_initial_retry: bool = False):
    fields = self.m.buildbucket.DEFAULT_FIELDS | {'tags'}
    try:
      if self.m.conductor.enabled and self.m.conductor.collect_config(
          collect_name):
        bbids = self.m.conductor.collect(collect_name, build_ids,
                                         timeout=60 * 60 * 36,
                                         initial_retry=conductor_initial_retry)
        return self.m.buildbucket.get_multi(
            bbids, step_name='get', url_title_fn=self.m.naming.get_build_title,
            fields=fields).values()
      return self.m.buildbucket.collect_builds(
          build_ids, timeout=60 * 60 * 36, step_name='collect',
          url_title_fn=self.m.naming.get_build_title, fields=fields).values()
    except StepFailure:
      return self.m.buildbucket.get_multi(
          build_ids, step_name='get',
          url_title_fn=self.m.naming.get_build_title, fields=fields).values()

  def _collect_value(
      self,
      build: build_pb2.Build,
      child_specs_dict: Dict[str, BuilderConfig.Orchestrator.ChildSpec],
      child_targets_dict: Dict[str, BuilderConfig.Orchestrator.ChildSpec],
      forced_testable_builders: List[str],
  ) -> BuilderConfig.Orchestrator.ChildSpec:
    """Returns whether the orchestrator should collect the build, and when.

    Args:
      build: the build to check whether to collect.
      child_specs_dict: mapping of builder name to ChildSpec.
      child_targets_dict: fuzzy mapping of build_target to ChildSpec.
        Fuzzy in the sense that it just chops off from the last '-' to the end
        of the builder name. Intended to pick up the *-snapshot cases. See more
        below.
      forced_testable_builders: The list of builders for which additional
        testing was defined via footer.

    Returns:
      (BuilderConfig.Orchestrator.ChildSpec) Whether to collect the build, and
      when.
    """
    values = BuilderConfig.Orchestrator.ChildSpec

    if build.builder.builder in forced_testable_builders:
      return values.COLLECT

    # For Chrome PUpr Uprev CLs, set the collect value of the additional
    # non-critical builders to NO_COLLECT.
    if build.builder.builder in self.m.build_plan.additional_chrome_pupr_builders:
      return values.NO_COLLECT

    ret = values.COLLECT
    child_spec = child_specs_dict.get(build.builder.builder)
    if not child_spec:
      # Missed lookup, the existing build name was not a name in child_specs.
      # The usual case could be existing build has a *-snapshot name but the
      # orchestrator's child has a *-postsubmit name, or a slim-cq build which
      # doesn't have an explicit ChildSpec.
      build_target = self._get_property(
          '$chromeos/build_menu.build_target.name', build.input.properties)
      if build_target:
        child_spec = child_targets_dict.get(build_target)

    if child_spec:
      return child_spec.collect_handling or ret
    # Missed lookup even after fallback for *-snapshot.
    return ret

  def run_follow_on_orchestrator(self, check_failures=False):
    """Run the follow_on_orchestrator, if any.  Wait if necessary."""
    follower = self.config.orchestrator.follow_on_orchestrator
    if not self.builds_status.fatal_failures and follower.name:
      self.schedule_wait_build(follower.name, follower.await_completion,
                               check_failures=check_failures,
                               step_name='run follow on orchestrator')

  def schedule_wait_build(self, builder, await_completion=False,
                          properties=None, check_failures=False, step_name=None,
                          timeout_sec=None):
    """Schedule a builder, and optionally await completion.

    Args:
      builder (str): The name of the builder: one of project/bucket/builder,
        bucket/builder, or builder.
      await_completion (bool): Whether to await completion.
      properties (dict): Dictionary of input properties for the builder.
      check_failures (bool): Whether or not failures accumulate in
        builds_status.  This is only used if await_completion is True.
      step_name (str): Name for the step, or None.
      timeout_sec (int): Timeout for the builder, in seconds.

    Returns:
      (Build): The build that was scheduled, and possibly waited for.
    """
    timeout_sec = timeout_sec or 60 * 60 * 36
    step_name = step_name or 'run %s' % builder
    with self.m.step.nest(step_name) as pres:
      # Separate out any project/bucket in the builder name.
      parts = builder.split('/', 2)
      project = self.m.buildbucket.INHERIT if len(parts) < 3 else parts[-3]
      bucket = self.m.buildbucket.INHERIT if len(parts) < 2 else parts[-2]
      builder = parts[-1]

      # The builder may or may not be in the same bucket as us, and the
      # gitiles_commit and gerrit_changes that we are using may have derived
      # from our builder config, rather than buildbucket properties.  Pass the
      # actual answers to schedule_request.
      props = self.m.cros_infra_config.props_for_child_build
      props.update(self.m.cv.props_for_child_build)
      props.update(properties or {})
      tags = self.m.cros_tags.make_schedule_tags(self.gitiles_commit)
      exps = self.m.cros_infra_config.experiments_for_child_build
      req = self.m.buildbucket.schedule_request(
          gitiles_commit=self.gitiles_commit, project=project, bucket=bucket,
          builder=builder, gerrit_changes=self.gerrit_changes, critical=True,
          experiments=exps, properties=props, tags=tags,
          inherit_buildsets=False)
      title_fn = self.m.naming.get_build_title
      build = self.m.buildbucket.schedule([req], url_title_fn=title_fn)[0]
      build_id = build.id
      url = self.m.buildbucket.build_url(build_id=build_id)
      pres.links[title_fn(build)] = url

      # Are we supposed to wait?
      if await_completion:
        fields = self.m.buildbucket.DEFAULT_FIELDS | {'tags'}
        try:
          build = list(
              self.m.buildbucket.collect_builds([build_id], timeout=timeout_sec,
                                                step_name='collect',
                                                url_title_fn=title_fn,
                                                fields=fields).values())[0]
        except StepFailure:
          build = list(
              self.m.buildbucket.get_multi([build_id], step_name='get',
                                           url_title_fn=title_fn,
                                           fields=fields).values())[0]

        failures = (
            self.m.failures.get_build_results([build]).failures
            if check_failures else [])
        self._builds_status.update([build], failures)
      return build

  def _gerrit_changes_in_snapshot(self) -> List[common_pb2.GerritChange]:
    """Find the changes landed in the orchestrator's snapshot commit.

    Requires that self.gitiles_commit is set and refers to a
    snapshot commit created by an Annealing builder.

    Specifically, this method looks up the Annealing builder with
    published_snapshot_id == self.gitiles_commit.id, and parses the
    found_gerrit_changes output property. Note that if the found Annealing
    builder didn't set this output property, this method will fail.
    """
    with self.m.step.nest('find changes in snapshot') as pres:
      assert self.gitiles_commit, '_gerrit_changes_in_snapshot should only be called when gitiles_commit is set'
      annealing_build = self.m.cros_history.get_annealing_from_snapshot(
          self.gitiles_commit.id)

      if not annealing_build:
        raise RuntimeError(
            f'no annealing build found for snapshot_id {self.gitiles_commit.id}'
        )

      changes = []
      for change_str in annealing_build.output.properties[
          'found_gerrit_changes']:
        change = common_pb2.GerritChange()
        changes.append(json_format.Parse(change_str, change))

      pres.step_text = f'found {len(changes)} changes from snapshot {self.gitiles_commit.id}'

      return changes

  def plan_and_run_tests(
      self,
      testable_builds: Optional[List[build_pb2.Build]] = None,
      container_metadata: Optional[ContainerMetadata] = None,
      ignore_gerrit_changes: bool = False,
  ) -> BuildsStatus:
    """Plan, schedule, and run tests.

    Run tests on the testable_builds identified by plan_and_run_children.

    Args:
      testable_builds: The list of builds to consider or None to use the
        current results.
      container_metadata: Information on container images used for test
        execution.
      ignore_gerrit_changes: Whether to drop gerrit changes from the test plan
        request, primarily used for tryjobs (which are release builds and thus
        shouldn't test based on any patches applied).

    Returns:
      BuildsStatus updated with any test failures.
    """
    # allowlist None means nothing is blocked from being critical.
    # We want this behavior if we're not on release.
    build_target_critical_allowlist = None
    if self._is_release_orchestrator:
      if self.m.skylab.qs_account in self._properties.retry_allowlist_qs_account:
        build_target_critical_allowlist = self._properties.retry_allowlist_build_target
      else:
        # Nothing should be critical.
        build_target_critical_allowlist = []

    self.m.skylab.apply_qs_account_overrides(self.gerrit_changes)
    gerrit_changes = [] if ignore_gerrit_changes else self.gerrit_changes

    # If this is a snapshot orchestrator, it shouldn't have any input changes.
    # Instead, lookup the gerrit changes landed in the snapshot, and test plan
    # based on these changes.
    #
    # TODO(b/289227008): Snapshot should run the base snapshot testing in
    # addition to the testing based on the snapshot CLs.
    if self.is_snapshot_orchestrator and (
        'chromeos.orch_menu.plan_tests_using_snapshot'
        in self.m.cros_infra_config.experiments):
      assert not gerrit_changes, 'gerrit_changes are not expected on the snapshot orchestrator'
      gerrit_changes = self._gerrit_changes_in_snapshot()

    test_failures = self.m.cros_test_proctor.run_proctor(
        testable_builds or self._builds_status.testable_builds,
        self.gitiles_commit,
        gerrit_changes,
        self._properties.enable_history,
        require_stable_devices=self.config.orchestrator.require_stable_devices,
        run_async=self._properties.run_tests_async,
        container_metadata=container_metadata,
        use_test_plan_v2=gerrit_changes and
        self.m.cros_test_plan_v2.enabled_on_changes(gerrit_changes),
        build_target_critical_allowlist=build_target_critical_allowlist,
    )
    self._builds_status.update([], test_failures)

    return self._builds_status

  def _collect_remaining_children(
      self,
      step_name: str = 'final build collect',
      no_nest: bool = False,
  ) -> BuildsStatus:
    """Collect any remaining children.

    Args:
      step_name: The name for the step.
      no_nest: If true, no nested step will be created.

    Returns:
      The current status of the builds.
    """
    if self._builds_status.running_builds:
      with contextlib.nullcontext() if no_nest else self.m.step.nest(step_name):
        completed_builds = self._collect_builds(
            [b.id for b in self._builds_status.running_builds])
        self._collect_and_check_build_results(completed_builds)
        if self._test_data.enabled:
          assert len(self._builds_status.running_builds) == 0
        self.m.greenness.update_build_info(completed_builds)
        self.m.greenness.print_step()

    return self._builds_status

  def _get_property(self, pathspec, props):
    """Get a value from a property by pathspec.

      Input and output properties are protobuffer.Struct instances, so
      normal python .get() methods don't work on them, so we have to walk the
      struct and check for presence of a key to safely retrieve it.

      Args:
        pathspec (str): Dotted field names to get, eg: build_target.name.
        props (Struct): Input or output properties.

      Return:
        Value of field if found, otherwise None.
      """
    obj = props
    for key in pathspec.split('.'):
      obj = obj[key] if key in obj else []
    return obj or None

  def aggregate_metadata(self, child_builds):
    """Aggregate metadata payloads from children.

    Pull metadata message of each type from children and merge the messages
    together.  Upload the resulting message as our own metadata.

    Args:
      child_builds ([BuildStatus]): BuildStatus instances for child builds

    Returns:
      (ContainerMetadata): Aggregated container metadata
    """
    # Iterate over each metadata payload defined in the metadata module.
    with self.m.step.nest('aggregating metadata') as aggregate_step:
      for metadata_info in self.m.metadata.METADATA_PAYLOADS.values():
        aggregated = metadata_info.msgtype()

        # For each child build we were given.
        step_name = '{} metadata'.format(metadata_info.name)
        with self.m.step.nest(step_name) as payload_step:

          def fail_parent_steps(summary=None):
            """Helper to fail higher steps and set step summary text."""
            # pylint: disable=cell-var-from-loop
            for step in [payload_step, aggregate_step]:
              step.status = self.m.step.FAILURE
              step.step_summary_text = summary or ''

          skipped = []
          for build in child_builds:

            step_name = 'processing {}'.format(build.builder.builder)
            with self.m.step.nest(step_name) as child_step:
              # If no build-target is set on the child build, then it's not an
              # actual build (not compiling an image), so skip it.
              input_props = build.input.properties
              build_target = self._get_property('build_target.name',
                                                input_props)
              if not build_target:
                child_step.step_summary_text = 'no build-target set, skipping'
                continue

              # If the child wasn't asked to build containers then skip it.
              container_version_format = self._get_property(
                  '$chromeos/build_menu.container_version_format',
                  input_props,
              )
              if not container_version_format:
                child_step.step_summary_text = (
                    'containers not configured, skipping')
                skipped.append(
                    (build.builder.builder, 'containers not configured'))
                continue

              # Grab artifact bucket and path from output properties of child
              # and use them to piece together the full path to the metadata
              # payload.
              output_props = build.output.properties
              gs_bucket = self._get_property('artifacts.gs_bucket',
                                             output_props)
              gs_path = self._get_property('artifacts.gs_path', output_props)

              if not (gs_bucket and gs_path):
                child_step.step_summary_text = 'no artifacts path, skipping'
                skipped.append((build_target, 'no artifacts path'))
                continue

              # Download the build's metadata payload.
              payload_path = self.m.metadata.gspath(metadata_info, gs_bucket,
                                                    gs_path)
              result = self.m.gsutil.cat(
                  payload_path,
                  name='reading payload for {}'.format(build_target),
                  stdout=self.m.raw_io.output(),
                  ok_ret=(0, 1),
              )

              if result.retcode != 0:
                # If we fail to download the metadata but the child build failed
                # overall, then we didn't build the containers but it's not an
                # error.  Containers for failed builds are a nice-to-have not
                # a requirement.
                if build.status != common_pb2.Status.SUCCESS:
                  child_step.status = self.m.step.SUCCESS
                  child_step.step_summary_text = (
                      'no metadata but build failed, ignoring.')
                  skipped.append((build_target, 'no metadata on failed build'))
                else:
                  child_step.status = self.m.step.FAILURE
                  child_step.step_text = 'failed to download'
                  fail_parent_steps(
                      'one or more child payloads failed to download')
                continue

              # Decode the child payload and log any parsing errors that occur,
              # but don't allow it to fail the overall build.
              payload = result.stdout
              try:
                message = json_format.Parse(payload, metadata_info.msgtype())
              # pylint: disable=broad-except
              except Exception as ex:
                child_step.status = self.m.step.FAILURE
                child_step.step_text = 'failed to parse'
                payload_step.logs['proto error'] = str(ex)
                fail_parent_steps('one or more child payloads failed to parse')
                continue

              aggregated.MergeFrom(message)

          payload_step.logs['skipped build info'] = '\n'.join(
              '%s - %s' % skipped_build for skipped_build in sorted(skipped))

        # TODO(b/204184594): Due to an issue in builder_config, we can't set an
        # artifacts path for orchestrators, so we'll hardcode the image-archive
        # bucket here but should use the configured bucket once it's fixed.
        staging = self.m.cros_infra_config.is_staging
        gs_bucket = ('staging-' if staging else '') + 'chromeos-image-archive'

        # All child payloads should be merged into 'aggregated' now, so write
        # it to our bucket as just another set of metadata.
        gs_path = self.m.cros_artifacts.upload_metadata(
            metadata_info.name,
            self.m.build_menu.config_or_default.id.name, # eg: cq-orchestrator
            '', # orchestrators have no build target
            gs_bucket,
            metadata_info.filename,
            aggregated,
        )

        aggregate_step.links['{} metadata (gs)'.format(metadata_info.name)] = (
            self.m.path.join(
                'https://console.cloud.google.com/storage/browser/_details',
                gs_bucket,
                gs_path,
            ))

        aggregate_step.logs['{} metadata (log)'.format(metadata_info.name)] = \
          json_format.MessageToJson(aggregated)

    return aggregated

  def _get_child_builds(self):
    """
    Get the child builders of current build.

    Returns:
      (list[Build]): List of child builds.
    """
    current_build = self.m.buildbucket.build
    # Do not want to search child builds for led job.
    children = []
    if current_build.id:
      predicate = builds_service_pb2.BuildPredicate(
          tags=self.m.buildbucket.tags(
              parent_buildbucket_id=str(current_build.id)))
      predicate.builder.project = current_build.builder.project
      children = self.m.buildbucket.search(predicate,
                                           fields=CHILD_BUILD_SEARCH_FIELDS)
    return children

  def add_child_info_to_output_property(
      self, relevant_child_builder_names: List[str] = None):
    """Add child information to output property of current build.

    Args:
      relevant_builder_names: List of relevant child builders.
    """
    relevant_child_builder_names = (
        relevant_child_builder_names or self._relevant_child_builder_names)
    child_builds = self._get_child_builds()
    child_build_info = []
    # TODO(b/266749698): Deprecate child_build_ids for child_build_info.
    for b in child_builds:
      child_build_dict = json_format.MessageToDict(b)
      # Add collect handling information.
      child_build_dict['collect_value'] = self._builder_to_collect_value[
          b.builder.builder]
      # Add whether this builder was tested in this run.
      child_build_dict['tested_in_this_run'] = (
          b.builder.builder
          in self.m.cros_test_proctor.builders_tested_in_this_run)
      # Add whether this builder was relevant.
      # This is only applicable to CQ and Snapshot.
      if self.is_cq_orchestrator or self.is_snapshot_orchestrator:
        child_build_dict['relevant'] = (
            b.builder.builder in relevant_child_builder_names)
      # If running unit tests async, add the time the child build was elegible
      # for collection.
      if 'image_artifacts_uploaded_time' in b.output.properties:
        child_build_dict['image_artifacts_uploaded_time'] = b.output.properties[
            'image_artifacts_uploaded_time']
      # Add whether this builder failed to emerge any packages.
      if 'package_failures' in b.output.properties:
        child_build_dict['package_failures'] = json_format.MessageToDict(
            b.output.properties['package_failures'])
      if 'output' in child_build_dict:
        del child_build_dict['output']

      child_build_info.append(child_build_dict)

    if child_builds:
      child_build_ids = [str(b.id) for b in child_builds]
      self.m.easy.set_properties_step(child_builds=child_build_ids)
      self.m.easy.set_properties_step(
          child_build_info=sorted(child_build_info,
                                  key=lambda b: b['builder']['builder']))

  def categorize_builds_by_collect_handling(
      self, child_specs: List[BuilderConfig.Orchestrator.ChildSpec],
      builds: List[build_pb2.Build]
  ) -> Dict[BuilderConfig.Orchestrator.ChildSpec.CollectHandling.Value,
            List[build_pb2.Build]]:
    """Group builds by CollectHandling value.

    Args:
      child_specs: The list of ChildSpecs used for build planning.
      builds: The list of builds spawned by this CQ run.

    Returns:
      A dict mapping CollectHandling to the list of builds which fall into that
          category.
    """
    with self.m.step.nest('categorize builds by collect handling') as pres:
      if (self.m.cv.active and self.gerrit_changes and
          self.m.cros_test_plan_v2.enabled_on_changes(self.gerrit_changes)):
        collect_when_dict = self._categorize_builds_by_collect_handling_using_coverage_rules(
            builds)
      else:
        collect_when_dict = self._categorize_builds_by_collect_handling_using_child_specs(
            child_specs, builds)

      for collect_value, _builds in collect_when_dict.items():
        for b in _builds:
          self._builder_to_collect_value[
              b.builder.
              builder] = BuilderConfig.Orchestrator.ChildSpec.CollectHandling.Name(
                  collect_value)

        pres.logs[BuilderConfig.Orchestrator.ChildSpec.CollectHandling.Name(
            collect_value)] = sorted([b.builder.builder for b in _builds])

      return collect_when_dict

  def _categorize_builds_by_collect_handling_using_child_specs(
      self, child_specs: List[BuilderConfig.Orchestrator.ChildSpec],
      builds: List[build_pb2.Build]
  ) -> Dict[BuilderConfig.Orchestrator.ChildSpec.CollectHandling.Value,
            List[build_pb2.Build]]:
    """Group builds by CollectHandling using the value in their ChildSpec.

    Args:
      child_specs: The list of ChildSpecs used for build planning.
      builds: The list of builds spawned by this CQ run.

    Returns:
      A dict mapping CollectHandling to the list of builds which fall into that
          category.
    """
    if self.m.cv.active and self.gerrit_changes:
      forced_testable_builders = self.m.cros_cq_additional_tests.get_additional_test_builders(
          builds, self.gerrit_changes)
    else:
      forced_testable_builders = []

    collect_when_dict = defaultdict(list)
    child_specs_dict = {cs.name: cs for cs in child_specs}
    child_targets_dict = {cs.name.rsplit('-', 1)[0]: cs for cs in child_specs}
    for b in builds:
      collect_value = self._collect_value(b, child_specs_dict,
                                          child_targets_dict,
                                          forced_testable_builders)
      collect_when_dict[collect_value].append(b)
    return collect_when_dict

  def _categorize_builds_by_collect_handling_using_coverage_rules(
      self, builds: List[build_pb2.Build]
  ) -> Dict[BuilderConfig.Orchestrator.ChildSpec.CollectHandling.Value,
            List[build_pb2.Build]]:
    """Group builds by CollectHandling using CoverageRules.

    Use the relevant CoverageRules for the Gerrit Changes applied to the CQ
    run and the criticality of the builders to group builds based on when they
    should be collected.

    Groupings:
      * NO_COLLECT: Build is non-critical.
      * COLLECT: Build is testable in this run.
      * COLLECT_AFTER_HW_TESTS: Build is critical but not testable.

    Args:
      builds: The list of builds spawned by this CQ run.

    Returns:
      A dict mapping CollectHandling to the list of builds which fall into that
          category.
    """
    testable_builders = None
    with self.m.failures.ignore_exceptions():
      testable_builders = set(
          self.m.cros_test_proctor.get_testable_builders(
              self.gerrit_changes, builds))
    if testable_builders is None:
      # If there is a failure in calling testplan, default to collecting all
      # critical child builds. As of now, all non-critical CQ child builds are
      # special non-image builders which should not need end-to-end testing.
      testable_builders = [
          b.builder.builder for b in builds if self.m.buildbucket.is_critical(b)
      ]
    else:
      forced_testable_builders = self.m.cros_cq_additional_tests.get_additional_test_builders(
          builds, self.gerrit_changes)
      testable_builders.update(set(forced_testable_builders))

    collect_when_dict = defaultdict(list)
    for b in builds:
      if not self.m.buildbucket.is_critical(b):
        collect_when_dict[
            BuilderConfig.Orchestrator.ChildSpec.NO_COLLECT].append(b)
      elif b.builder.builder in testable_builders:
        collect_when_dict[BuilderConfig.Orchestrator.ChildSpec.COLLECT].append(
            b)
      else:
        collect_when_dict[BuilderConfig.Orchestrator.ChildSpec
                          .COLLECT_AFTER_HW_TEST].append(b)

    return collect_when_dict
