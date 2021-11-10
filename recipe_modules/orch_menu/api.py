# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API providing a menu for orchestrator steps"""

from __future__ import division

from collections import defaultdict, namedtuple
import contextlib

from google.protobuf import json_format
from recipe_engine.recipe_api import RecipeApi, StepFailure
from PB.chromiumos.builder_config import BuilderConfig
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.chrome.chrome import ChromeProperties

_manifest_info = namedtuple('_manifest_info',
                            ['name', 'gitiles_commit', 'path', 'url'])

# GS path for internal buildspecs.
BUILDSPEC_GS_PATH = 'buildspecs-internal/release/'


class BuildsStatus(object):
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
    failure_updates += unchanged_failures
    self.failures = failure_updates

  def _is_testable(self, build):
    """Whether the build is testable."""
    return (build.status == common_pb2.SUCCESS and
            self._configs.get(build.builder.builder))


class OrchMenuApi(RecipeApi):
  """A module with steps used by orchestrators.

  Orchestrators do not call other recipe modules directly: they always get there
  via this module, and are a simple sequence of steps.
  """

  def __init__(self, properties, *args, **kwargs):
    super(OrchMenuApi, self).__init__(*args, **kwargs)
    self._update_manifest_refs = False
    self._external_gitiles_commit = None
    # Our properties: OrchMenuProperties ($chromeos/orch_menu).
    self._properties = properties
    self._builds_status = BuildsStatus([], [], {})
    self._is_release_orchestrator = False
    self._is_postsubmit_orchestrator = False
    self._is_bisecting_orchestrator = False
    self._chromium_src_ref_cl_tag = None

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
    return self.m.cq.active and self.m.cq.run_mode == self.m.cq.DRY_RUN

  @property
  def builds_status(self):
    return self._builds_status

  @property
  def is_release_orchestrator(self):
    return self._is_release_orchestrator

  @property
  def is_postsubmit_orchestrator(self):
    return self._is_postsubmit_orchestrator

  @property
  def is_bisecting_orchestrator(self):
    return self._is_bisecting_orchestrator

  @property
  def chromium_src_ref_cl_tag(self):
    return self._chromium_src_ref_cl_tag

  def chrome_module_child_props(self):
    return json_format.MessageToDict(
        ChromeProperties(version=self._chromium_src_ref_cl_tag))

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
  def setup_orchestrator(self, missing_ok=False, test_footers=None):
    """Initial setup steps for the orchestrator.

    This context manager returns with all of the contexts that the orchestrator
    needs to have when it runs, for cleanup to happen properly.

    If appropriate, any inflight orchestrator has finished before we return.

    Args:
      missing_ok (bool): Whether it is OK if no config is found.  This can be
        used by the caller to have a builder with no config report FAILURE
        (False), or SUCCESS (True).
      test_footers (str): test Cr-External-Snapshot footer data(values separated
          by newlines), or None.

    Raises:
      StepFailure if no config is found and |missing_ok| is False.

    Returns:
      BuilderConfig or None, with an active context.
    """
    with self.m.bot_cost.cq_run_cost_context(), \
        self.m.cros_source.checkout_overlays_context(snapshot_mount=True):
      with self.m.step.nest('set up orchestrator') as presentation:
        self._validate_properties()
        config = self.m.cros_source.configure_builder(
            self.m.buildbucket.gitiles_commit,
            self.m.buildbucket.build.input.gerrit_changes)

        self.m.cros_bisect.set_orchestrator_bisect_builder()
        presentation.links['manifest snapshot revision'] = (
            self.m.gitiles.file_url(self.gitiles_commit, 'snapshot.xml'))

        external_commit = self.m.cros_source.checkout_manifests(
            is_staging=self.m.cros_infra_config.is_staging,
            checkout_external=self._update_manifest_refs,
            test_footers=test_footers)
        self._external_gitiles_commit = external_commit

        # We cannot push manifest refs to unpinned branches.
        self._update_manifest_refs &= (external_commit.id != '')

        if not config and not missing_ok:
          raise StepFailure('Missing configuration for {}'.format(
              self.m.buildbucket.builder_name))

        # If release orchestrator, full checkout and pin manifest.
        if config and config.id.type == BuilderConfig.Id.RELEASE:
          self._is_release_orchestrator = True
          with self.m.workspace_util.sync_to_commit(
              staging=self.m.cros_infra_config.is_staging):
            self.m.cros_version.bump_version()
            self.m.cros_release.create_releasespec(
                gs_location=BUILDSPEC_GS_PATH)

        if self.m.buildbucket.build.builder.builder.endswith(
            'postsubmit-orchestrator'):
          self._is_postsubmit_orchestrator = True

        if self.m.buildbucket.build.builder.builder.endswith(
            'bisecting-orchestrator'):
          self._is_bisecting_orchestrator = True

        self._chromium_src_ref_cl_tag = self.m.cros_tags.cq_cl_tag_value(
            'chromium_src_ref', self.m.buildbucket.build.tags)

      if config:
        # Update the start ref to indicate we've begun processing the snapshot.
        self._push_manifest_refs(self._properties.update_manifest_refs.start)

        if self.gerrit_changes:
          # Any changes we have must be submittable.
          self.m.gerrit.assert_changes_submittable(self.gerrit_changes)

      # If we are waiting on inflight orchestrators, do that now.
      self._wait_for_inflight_orchestrator()

      # Yield while inside of the bot_cost.cq_run_cost_context.
      yield config

  def create_recipe_result(self):
    """Create the correct return value for RunSteps.

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
      self._non_critical_test_check()
      self.m.greenness.print_step()
      # Set child output ids if any
      self.m.build_menu.add_child_build_ids_to_output_property()
    return self.m.failures.aggregate_failures(self.builds_status.failures)

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
          raise StepFailure('%s is out of range [0.0, 1.0] at %s' %
                            (field.name, value))
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
        with self.m.step.nest('update %s ref %s' % (manifest.name, ref)), \
            self.m.context(cwd=manifest.path):
          self.m.git.push(manifest.url,
                          "%s:%s" % (manifest.gitiles_commit.id, ref))

  def _update_test_summary(self):
    """Updates criticality on the output test_summary"""
    # Output the number of updates in order to measure impact.
    update_count = 0
    non_fatal_failures = [
        f.id for f in self.builds_status.failures if not f.fatal
    ]
    test_summary = self.m.cros_test_proctor.test_summary
    for test in test_summary:
      if test['status'] == 'FAILURE' and test['critical']:
        if test.get('name') in non_fatal_failures:
          test['critical'] = False
          update_count += 1
    if update_count:
      self.m.step.active_result.presentation.properties[
          'test_criticality_update_count'] = update_count
      self.m.cros_test_proctor.test_summary = test_summary

  def _non_critical_test_check(self):
    """Update failures in builds_status based on the current criticality."""
    with self.m.step.nest('non-critical test check') as pres:
      # Avoid regenerating the test plan if there are no critical test failures.
      if not any(
          f.kind.endswith('test') and f.fatal
          for f in self.builds_status.failures):
        pres.step_text = 'no critical test failures'
        return

      refreshed_test_plan = self.m.cros_test_plan.generate(
          self.builds_status.completed_builds, self.gerrit_changes,
          self.gitiles_commit)

      test_plan_summary = self.m.cros_test_plan.get_test_plan_summary(
          refreshed_test_plan)

      updated_failures = self.m.failures.update_non_critical_test_failures(
          self.builds_status.failures, test_plan_summary)

      self.builds_status.update(failures=updated_failures)
      self._update_test_summary()

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
      if not len(running_builds):
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
      # Don't run builds if testing LTS chrome. https://crbug.com/1186358
      # Delete this hack once https://crbug.com/1186852 is fixed.
      if (self.m.buildbucket.build.builder.builder.startswith('lts-cq-') and
          self.m.cros_tags.has_entry('cq_cl_tag',
                                     'pupr:chromeos-base/chromeos-chrome',
                                     self.m.buildbucket.build.tags)):
        return self._builds_status
      completed_builds, collect_after = self._filter_schedule_wait_builds(
          pres, self._bisect_builder_child_specs(),
          extra_props=extra_child_props)

    self._collect_and_check_build_results(
        completed_builds, results_step_name=results_step_name,
        check_critical_step_name=check_critical_step_name)

    self._builds_status.update(running=collect_after)
    self.m.greenness.update_build_info(completed_builds)

    # Determine the failure ratio and see if we should update the ref.
    # If we didn't complete a build, call it success.
    failure_ratio = (
        len(self._builds_status.fatal_failures) /
        max(1, len(self._builds_status.completed_builds)))
    if failure_ratio <= self._properties.update_manifest_refs.max_build_failure_ratio:
      # If we've made it this far, update the build success manifest ref.
      self._push_manifest_refs(self._properties.update_manifest_refs.build)

    return self._builds_status

  def _collect_and_check_build_results(self, builds, results_step_name=None,
                                       check_critical_step_name=None):
    # Assume relevant if the child doesn't have the relevant_build prop.
    relevant = lambda build: ('relevant_build' not in build.output.properties or
                              build.output.properties['relevant_build'])
    with self.m.step.nest(results_step_name or 'check build results') as pres:
      relevant_builds = [
          x.builder.builder
          for x in self._builds_status.completed_builds
          if relevant(x)
      ]
      for build in builds:
        if build.status in (common_pb2.STARTED, common_pb2.SCHEDULED):
          pres.text = 'some builds are running/pending'
        if relevant(build):
          relevant_builds.append(build.builder.builder)
      pres.logs['relevant_builds'] = sorted(relevant_builds or
                                            ['no relevant builds'])
      self.m.easy.set_properties_step(
          child_builds_relevant=len(relevant_builds))
      failures = self.m.failures.get_build_failures(builds)
      self.builds_status.update(completed=builds, failures=failures)

    # Recheck the BuilderConfigs at HEAD to see if any failed builds are now
    # non-critical.
    self._non_critical_build_check(
        check_critical_step_name or 'non-critical build check', builds,
        failures)

  def _bisect_builder_child_specs(self):
    """Get the child_spec list from cros_bisect.

    Returns:
      (list[BuilderConfig.Orchestrator.ChildSpec]) The list of child_specs.
    """
    return [
        BuilderConfig.Orchestrator.ChildSpec(
            name=cb,
            collect_handling=BuilderConfig.Orchestrator.ChildSpec.COLLECT)
        for cb in self.m.cros_bisect.get_test_child_builders()
    ] or self.config.orchestrator.child_specs

  def _filter_schedule_wait_builds(self, parent_step, child_specs,
                                   extra_props=None):
    """Find the builds we need, filter those already started, run, and collect.

    Most of the heavy lifting is done in get_build_plan.

    Args:
      parent_step (Step): the calling step, used for presentation purposes.
      child_specs (list(ChildSpec)): A list of child specs.
      extra_props (dict): Extra properties to append to child requests.

    Returns:
      (list[Build]) List of build results.
    """
    completed_builds, existing_builds, new_build_requests = (
        self.m.build_plan.get_build_plan(
            child_specs=child_specs,
            enable_history=self._properties.enable_history,
            gerrit_changes=self.gerrit_changes,
            internal_snapshot=self.gitiles_commit,
            external_snapshot=self.external_gitiles_commit))
    parent_step.presentation.step_text = ('{} new, {} recycled'.format(
        len(new_build_requests),
        len(completed_builds) + len(existing_builds)))

    log_msg = ''
    if new_build_requests:
      # Add in extra_props.
      if extra_props:
        for _, req in enumerate(new_build_requests):
          # Only set the value if it's not set already.
          # We don't want to clobber anything.
          for key, val in extra_props.items():
            if key not in req.properties:
              req.properties[key] = val
            elif req.properties[key] != val:
              log_msg = 'extra_props mismatch: [{}] = {} but had extra_prop value {}'.format(
                  key, req.properties[key], val)

      # Implement sleepy builds for GoB smoothing: crbug.com/1063143
      with self.m.step.nest('schedule new builds') as presentation:
        if log_msg:
          presentation.step_text = log_msg
        with self.m.buildbucket.with_host(self.m.buildbucket.HOST_PROD):
          for new_build_request in new_build_requests:
            # Request new builds and add to total existing.
            existing_builds += self.m.buildbucket.schedule(
                [new_build_request], url_title_fn=self.m.naming.get_build_title,
                step_name=new_build_request.builder.builder)
            if self._properties.stagger_children_seconds:
              self.m.time.sleep(self._properties.stagger_children_seconds)

    collect_when_dict = defaultdict(list)
    child_specs_dict = {cs.name: cs for cs in child_specs}
    child_targets_dict = {cs.name.rsplit('-', 1)[0]: cs for cs in child_specs}
    for b in existing_builds:
      collect_when_dict[self._collect_value(b.builder.builder, child_specs_dict,
                                            child_targets_dict)].append(b)

    # Collect all existing builds, add to completed builds
    build_ids = [
        b.id
        for b in collect_when_dict[BuilderConfig.Orchestrator.ChildSpec.COLLECT]
    ]
    completed_builds += self._collect_builds(build_ids)
    return completed_builds, collect_when_dict[
        BuilderConfig.Orchestrator.ChildSpec.COLLECT_AFTER_HW_TEST]

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

  def _collect_value(self, builder_name, child_specs_dict, child_targets_dict):
    """Returns whether the orchestrator should collect the build, and when.

    Args:
      builder_name (str): the name of the builder to check whether to collect.
      child_specs_dict (dict): mapping of builder name to ChildSpec.
      child_targets_dict (dict): fuzzy mapping of build_target to ChildSpec.
        Fuzzy in the sense that it just chops off from the last '-' to the end
        of the string. Intended to pick up the *-snapshot cases. See more below.

    Returns:
      (BuilderConfig.Orchestrator.ChildSpec) Whether to collect the build, and
      when.
    """
    values = BuilderConfig.Orchestrator.ChildSpec
    ret = values.COLLECT
    child_spec = child_specs_dict.get(builder_name)
    if not child_spec:
      # Missed lookup, the existing build name was not a name in child_specs.
      # The usual case would be existing build has a *-snapshot name but the
      # orchestrator's child has a *-postsubmit name.
      # TODO(crbug/991996): Refactor: use something other than string manip.
      child_spec = child_targets_dict.get(builder_name.rsplit('-', 1)[0])
    if child_spec:
      return child_spec.collect_handling or ret
    # Missed lookup even after fallback for *-snapshot.
    return ret

  def run_follow_on_orchestrator(self):
    """Run the follow_on_orchestrator, if any.  Wait if necessary."""
    follower = self.config.orchestrator.follow_on_orchestrator
    if not self.builds_status.fatal_failures and follower.name:
      self.schedule_wait_build(follower.name, follower.await_completion)

  def schedule_wait_build(self, builder, await_completion=False,
                          properties=None, check_failures=False, step_name=None,
                          timeout_sec=None):
    """Schedule a builder, and optionally await completion.

    Args:
      builder (str): The name of the builder: one of project/bucket/builder,
        bucket/builder, or builder.
      await_completion (bool): Wether to await completion.
      properties (dict): Dictionary of input properties for the builder.
      check_failures (bool): Whether or not failures accumulate in
        builds_status.  This is only used if await_completion is True.
      step_name (str): Name for the step, or None.
      timeout_sec (int): Timeout for the builder, in seconds.

    Returns:
      (Build): The build that was scheduled, and possibly waited for.
    """
    timeout_sec = timeout_sec or 60 * 60 * 36
    with self.m.step.nest(step_name or 'run follow on orchestrator') as pres:
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
      props.update(self.m.cq.props_for_child_build)
      props.update(properties or {})
      tags = self.m.cros_tags.make_schedule_tags(self.gitiles_commit)
      exps = self.m.cros_infra_config.experiments_for_child_build
      req = self.m.buildbucket.schedule_request(
          gitiles_commit=self.gitiles_commit, project=project, bucket=bucket,
          builder=builder, gerrit_changes=self.gerrit_changes, critical=True,
          experiments=exps, properties=props, tags=tags,
          inherit_buildsets=False)
      title_fn = self.m.naming.get_build_title
      [build] = self.m.buildbucket.schedule([req], url_title_fn=title_fn)
      url = self.m.buildbucket.build_url(build_id=build.id)
      pres.presentation.links[title_fn(build)] = url

      # Are we supposed to wait?
      if await_completion:
        fields = self.m.buildbucket.DEFAULT_FIELDS | {'tags'}
        try:
          builds = self.m.buildbucket.collect_builds([build.id],
                                                     timeout=timeout_sec,
                                                     step_name='collect',
                                                     url_title_fn=title_fn,
                                                     fields=fields).values()
        except StepFailure:
          builds = self.m.buildbucket.get_multi([build.id], step_name='get',
                                                url_title_fn=title_fn,
                                                fields=fields).values()

        failures = (
            self.m.failures.get_build_failures(builds)
            if check_failures else [])
        self._builds_status.update(builds, failures)
      return builds[0]

  def plan_and_run_tests(self, testable_builds=None):
    """Plan, schedule, and run tests.

    Run tests on the testable_builds identified by plan_and_run_children.

    Args:
      testable_builds (list[Build]): The list of builds to consider,
        or None to use the current results.

    Returns:
      (BuildsStatus): The current status of the builds.
    """
    # Is the build tagged as overriding the PCQ quota scheduler account?
    if self.m.cros_tags.has_entry('cq_cl_tag',
                                  'pupr:chromeos-base/chromeos-chrome',
                                  self.m.buildbucket.build.tags):
      self.m.skylab.set_qs_account('pupr')

    test_failures = self.m.cros_test_proctor.run_proctor(
        testable_builds or self._builds_status.testable_builds,
        self.gitiles_commit, self.gerrit_changes,
        self._properties.enable_history,
        run_async=self._properties.run_tests_async)
    self._builds_status.update([], test_failures)

    if not self._collect_remaining_children().fatal_failures:
      self._push_manifest_refs(self._properties.update_manifest_refs.test)

    return self._builds_status

  def _collect_remaining_children(self, step_name='final build collect'):
    """Collect any remaining children.

    Args:
      step_name (str): The name for the step.

    Returns:
      (BuildsStatus): The current status of the builds.
    """
    if self._builds_status.running_builds:
      with self.m.step.nest(step_name):
        completed_builds = self._collect_builds(
            [b.id for b in self._builds_status.running_builds])
        self._collect_and_check_build_results(completed_builds)
        self.m.greenness.update_build_info(completed_builds)
    return self._builds_status

  def aggregate_metadata(self, child_builds):
    """Aggregate metadata payloads from children.

    Pull metadata message of each type from children and merge the messages
    together.  Upload the resulting message as our own metadata.

    Args:
      child_builds ([BuildStatus]): BuildStatus instances for child builds
    """

    def get_property(pathspec, props):
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
              step.step_summary_text = summary or ""

          skipped = []
          for build in child_builds:

            step_name = 'processing {}'.format(build.builder.builder)
            with self.m.step.nest(step_name) as child_step:
              # If no build-target is set on the child build, then it's not an
              # actual build (not compiling an image), so skip it.
              input_props = build.input.properties
              build_target = get_property('build_target.name', input_props)
              if not build_target:
                child_step.step_summary_text = 'no build-target set, skipping'
                continue

              # If the child wasn't asked to build containers then skip it.
              container_version_format = get_property(
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
              gs_bucket = get_property('artifacts.gs_bucket', output_props)
              gs_path = get_property('artifacts.gs_path', output_props)

              if not (gs_bucket and gs_path):
                child_step.step_summary_text = 'no artifacts path, skipping'
                skipped.append((build_target, 'no artifacts path'))
                continue

              payload_path = self.m.path.join(
                  gs_bucket,
                  gs_path,
                  self.m.metadata.gspath(metadata_info),
              )

              # Force path to have a gs:// prefix.
              prefix = '' if payload_path.startswith('gs://') else 'gs://'
              payload_path = prefix + payload_path

              # Download the build's metadata payload.
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
                payload_step.logs['proto error'] = str(ex)
                fail_parent_steps('one or more child payloads failed to parse')
                continue

              aggregated.MergeFrom(message)

          payload_step.logs['skipped build info'] = '\n'.join(
              "%s - %s" % skipped_build for skipped_build in sorted(skipped))

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
            "", # orchestrators have no build target
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
