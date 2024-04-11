# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API providing a menu for snapshot orchestrator steps"""

from __future__ import division

import contextlib
from collections import namedtuple
from typing import Any, Dict, List, Optional, Tuple

from google.protobuf import json_format

from PB.chromiumos.build.api.container_metadata import ContainerMetadata
from PB.chromiumos.builder_config import BuilderConfig
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_engine import result as result_pb2
from recipe_engine.engine_types import StepPresentation
from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure
from RECIPE_MODULES.chromeos.orch_menu.api import BuildsStatus

CHILD_BUILD_SEARCH_FIELDS = frozenset({
    'id', 'create_time', 'start_time', 'end_time', 'status', 'builder.bucket',
    'builder.builder', 'output.properties'
})

_manifest_info = namedtuple('_manifest_info',
                            ['name', 'gitiles_commit', 'path', 'url'])


class SnapshotOrchMenuApi(recipe_api.RecipeApi):
  """A module with steps used by orchestrators.

  Orchestrators do not call other recipe modules directly: they always get there
  via this module, and are a simple sequence of steps.
  """

  def __init__(self, properties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._update_manifest_refs = False
    self._external_gitiles_commit = None
    # Our properties: OrchMenuProperties ($chromeos/snapshot_orch_menu).
    self._properties = properties
    self._builds_status = BuildsStatus([], [], {})
    self._is_postsubmit_orchestrator = False
    self._relevant_child_builder_names = []

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
  def builds_status(self):
    return self._builds_status

  @property
  def is_postsubmit_orchestrator(self):
    return self._is_postsubmit_orchestrator

  @property
  def relevant_child_builder_names(self):
    return self._relevant_child_builder_names

  def _get_manifest_info(self, external=False):
    """Return information about a manifest repo.

    Args:
      external (bool): Whether the external manifest is wanted.

    Returns:
      None, or an object with attributes:
        name (str): display name for the manifest repo.
        gitiles_commit (GitilesCommit): commit for the repo.
        path (Path): Path to the checked out repo.
        url (str): URL for the repo.
    """
    manifest = self.m.src_state.internal_manifest
    commit = self.gitiles_commit
    if external:
      manifest = self.m.src_state.external_manifest
      commit = self._external_gitiles_commit
    return _manifest_info(manifest.relpath, commit, manifest.path, manifest.url)

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
        self._validate_properties()
        config = self.m.cros_source.configure_builder(
            self.m.buildbucket.gitiles_commit)

        presentation.links['manifest snapshot revision'] = (
            self.m.gitiles.file_url(self.gitiles_commit, 'snapshot.xml'))

        use_external = self.gitiles_commit.project == 'chromiumos/manifest'
        external_commit = self.m.cros_source.checkout_manifests(
            is_staging=self.m.cros_infra_config.is_staging,
            checkout_internal=not use_external,
            checkout_external=self._update_manifest_refs or use_external)
        self._external_gitiles_commit = external_commit

        # We cannot push manifest refs to unpinned branches.
        self._update_manifest_refs &= (external_commit.id != '')

        if self.m.buildbucket.build.builder.builder.endswith(
            'postsubmit-orchestrator'):
          self._is_postsubmit_orchestrator = True

      if config:
        # Update the start ref to indicate we've begun processing the snapshot.
        self._push_manifest_refs(self._properties.update_manifest_refs.start)

      # Yield while inside of the bot_cost.build_cost_context.
      yield config

  def create_recipe_result(self) -> result_pb2.RawResult:
    """Create the correct return value for RunSteps.

    Returns:
      (recipe_engine.result_pb2.RawResult) The return value for RunSteps.
    """
    if not self.builds_status.fatal_failures:
      self._push_manifest_refs(self._properties.update_manifest_refs.test)

    with self.m.step.nest('clean up orchestrator'):
      # Recheck the BuilderConfigs at HEAD, one last time, to see if any
      # failed builders are now noncritical.
      self._non_critical_build_check('final build criticality update',
                                     self.builds_status.completed_builds,
                                     self.builds_status.failures)
      self.m.cros_resultdb.apply_exonerated_exonerations(
          [self.m.cros_resultdb.current_invocation_id])
      # Do a final call to update_irrelevant_scores, to get the previous
      # greenness for any irrelevant builders. The previous call to
      # update_build_info may have only propagated build scores forward, since
      # it does not wait for the previous snapshot orchestrator to complete.
      self.m.greenness.update_irrelevant_scores()
      self.m.greenness.print_step()
      # Set child output ids if any
      self.m.orch_menu.add_child_info_to_output_property(
          self._relevant_child_builder_names)

    successes = {
        'build':
            self._count_successful_critical_builds(
                self.builds_status.completed_builds)
    }

    results = self.m.failures.Results(failures=self.builds_status.failures,
                                      successes=successes)

    raw_result = self.m.failures.aggregate_failures(results)
    return raw_result

  def _count_successful_critical_builds(self, builds):
    return len([
        b for b in builds
        if b.critical == common_pb2.YES and b.status == common_pb2.SUCCESS
    ])

  def _validate_properties(self):
    """Validate the orchestrator properties.

    Raises:
      StepFailure on errors.
    """
    # The only property we need to validate is update_manifest_refs, and we want
    # to validate all of them.
    for field, value in self._properties.update_manifest_refs.ListFields():
      if field.name == 'max_build_failure_ratio':
        if value < 0.0 or value > 1.0:
          raise StepFailure('{} is out of range [0.0, 1.0] at {!r}'.format(
              field.name, value))
      else:
        if not value.startswith('refs/heads/'):
          raise StepFailure('%s ref %s is missing refs/heads/' %
                            (field.name, value))
      self._update_manifest_refs = True

  def _push_manifest_refs(self, ref):
    """Update the remote ref (if any).

    If |ref| evaluates to False, do nothing.

    Args:
      ref (str): Ref to push to (possibly empty) or None
    """
    if self._update_manifest_refs and ref:
      for external in False, True:
        manifest = self._get_manifest_info(external)
        with self.m.step.nest('update %s ref %s' % (manifest.name, ref)) as pres, \
            self.m.context(cwd=manifest.path):
          try:
            self.m.git.push(manifest.url,
                            '%s:%s' % (manifest.gitiles_commit.id, ref))
          except self.m.step.StepFailure:
            # Making this fail silently because newer snapshot orchestrator can
            # update a ref before the older one.
            pres.status = self.m.step.WARNING
            pres.text = 'failed to push. continuing'

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
      collect_builds = self._filter_schedule_builds(
          pres, self._get_child_specs(), extra_props=extra_child_props)

      completed_builds = list(
          self._collect_builds([b.id for b in collect_builds]))
      self.m.orch_menu.add_child_info_to_output_property(
          self._relevant_child_builder_names)

    self._collect_and_check_build_results(
        completed_builds, results_step_name=results_step_name,
        check_critical_step_name=check_critical_step_name)

    self.m.greenness.update_build_info(completed_builds)
    self.m.greenness.print_step()

    # Use looks for green to determine if we should update the refs.
    # These steps are only run on snapshot-orchestrator.
    if self._update_manifest_refs and self._properties.update_manifest_refs.build:
      with self.m.failures.ignore_exceptions():
        with self.m.step.nest('update local greenness') as pres:
          should_update = self.m.greenness.is_green_for_local()
          if should_update:
            self._push_manifest_refs(
                self._properties.update_manifest_refs.build)
            # TODO: b/304592527 - Remove line below once green is set to
            # automatically track stable
            self._push_manifest_refs('refs/heads/green')
          should_update_bazel = self.m.greenness.is_green_for_local(
              is_bazel=True)
          if should_update_bazel:
            self._push_manifest_refs('refs/heads/stable-bazel')
          pres.step_text = f'should_update: {should_update}, should_update_bazel: {should_update_bazel}'
          self.output_local_greenness(should_update, should_update_bazel)

    return self._builds_status

  def output_local_greenness(self, should_update: bool,
                             should_update_bazel: bool) -> None:
    """Outputs info about local greenness."""
    local_greenness_output_dict = {}
    local_greenness_output_dict['updated'] = should_update
    local_greenness_output_dict['updated_bazel'] = should_update_bazel
    self.m.easy.set_properties_step(local_greenness=local_greenness_output_dict)

  def ps_relevant(self, build: build_pb2.Build) -> bool:
    """Whether the postsubmit child build was critical and relevant.

    Args:
      build: The child build.
    """
    for tag in build.tags:
      if tag.key == 'relevance':
        return tag.value == 'relevant'

    # If relevance tag is not set, assume relevance
    return True

  def _collect_and_check_build_results(self, builds, results_step_name=None,
                                       check_critical_step_name=None):
    with self.m.step.nest(results_step_name or 'check build results'):
      # Add the newly completed builds to build_status.
      self.builds_status.update(completed=builds)

      # Output information about child build relevancy.

      if self.config.id.type in [
          BuilderConfig.Id.POSTSUBMIT, BuilderConfig.Id.SNAPSHOT
      ]:
        self._relevant_child_builder_names = [
            x.builder.builder
            for x in self._builds_status.completed_builds
            if self.ps_relevant(x)
        ]
        ps_relevant_critical_builds = [
            x.builder.builder
            for x in self._builds_status.completed_builds
            if self.ps_relevant(x) and self.m.buildbucket.is_critical(x)
        ]
        if not ps_relevant_critical_builds:
          self.m.easy.set_properties_step(all_critical_builds_irrelevant=True)
          self.m.easy.set_properties_step(sheriff_ignore_build=True)

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
      A list of scheduled builds to be collected on.
    """
    _, new_build_requests = (
        self.m.build_plan.get_build_plan(
            child_specs=child_specs,
            enable_history=self._properties.enable_history,
            gerrit_changes=self.gerrit_changes,
            internal_snapshot=self.gitiles_commit,
            external_snapshot=self.external_gitiles_commit))
    parent_step.step_text = ('{} new'.format(len(new_build_requests)))

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

          for new_build_request in new_build_requests:
            builder_name = new_build_request.builder.builder
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

    self.m.orch_menu.add_child_info_to_output_property(
        self._relevant_child_builder_names)

    return new_builds

  def _collect_builds(self, build_ids):
    fields = self.m.buildbucket.DEFAULT_FIELDS | {'tags'}
    try:
      return self.m.buildbucket.collect_builds(
          build_ids, timeout=60 * 60 * 36, step_name='collect',
          url_title_fn=self.m.naming.get_build_title, fields=fields).values()
    except StepFailure:
      return self.m.buildbucket.get_multi(
          build_ids, step_name='get',
          url_title_fn=self.m.naming.get_build_title, fields=fields).values()

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
    self.m.skylab.apply_qs_account_overrides(self.gerrit_changes)
    gerrit_changes = [] if ignore_gerrit_changes else self.gerrit_changes

    # If this is a snapshot orchestrator, it shouldn't have any input changes.
    # Instead, lookup the gerrit changes landed in the snapshot, and test plan
    # based on these changes.
    #
    # TODO(b/289227008): Snapshot should run the base snapshot testing in
    # addition to the testing based on the snapshot CLs.
    if self.m.orch_menu.is_snapshot_orchestrator and (
        'chromeos.snapshot_orch_menu.plan_tests_using_snapshot'
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
    )
    self._builds_status.update([], test_failures)

    return self._builds_status
