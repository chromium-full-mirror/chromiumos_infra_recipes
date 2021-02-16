# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API providing a menu for orchestrator steps"""

from collections import defaultdict, namedtuple
import contextlib

from google.protobuf.json_format import MessageToDict
from google.protobuf.json_format import ParseDict

from recipe_engine.recipe_api import RecipeApi, StepFailure

from PB.chromiumos.builder_config import BuilderConfig
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.orch_menu.orch_menu import OrchMenuProperties

_manifest_info = namedtuple('_manifest_info',
                            ['name', 'gitiles_commit', 'path', 'url'])


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

  def update(self, completed, failures, configs=None, running=None):
    """Update the status.

    Add the new builds and failures to our attributes.  Remove completed builds
    from running list.

    Args:
      completed (list[Build]): The builds.
      failures (list[Failure]): The failures
      configs (dict{name: BuilderConfig}): Builder config dictionary.
      running (list[Build]): The still-running builds, or None.
    """
    completed_ids = set(b.id for b in completed)
    self._configs = configs or self._configs
    self.completed_builds += completed
    self.failures += failures
    # Remove any just completed builds from self.running_builds.
    self.running_builds = [
        b for b in self.running_builds if b.id not in completed_ids
    ]
    # Add any new running builds to self.running_builds.
    running_ids = set(b.id for b in self.running_builds)
    self.running_builds += [b for b in running or [] if not b.id in running_ids]

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

  def initialize(self):
    # Set the default buildbucket host for buildbucket calls.
    self.m.buildbucket.host = self.m.buildbucket.HOST_PROD_BEEFY

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
    return self.m.cq.state == self.m.cq.DRY

  @property
  def builds_status(self):
    return self._builds_status

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
        self.m.cros_source.checkout_overlays_context():
      with self.m.step.nest('set up orchestrator') as presentation:
        self._validate_properties()
        config = self.m.cros_infra_config.configure_builder(
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
          with self.m.workspace_util.sync_to_commit(
              staging=self.m.cros_infra_config.is_staging):
            self.m.cros_release.create_releasespec()

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

    # Recheck the BuilderConfigs at HEAD, one last time, to see if any
    # failed builders are now noncritical.
    result = self._non_critical_build_check('clean up orchestrator',
                                            self.builds_status.completed_builds,
                                            self.builds_status.failures)
    return self.m.failures.aggregate_failures(result.failures)

  def _validate_properties(self):
    """Validate the orchestrator properties.

    Raises:
      StepFailure on errors.
    """
    # The only property we need to validate is update_manifest_refs, and we want
    # to validate all of them.
    for ref, value in self._properties.update_manifest_refs.ListFields():
      if not value.startswith('refs/heads/'):
        raise StepFailure('%s ref %s is missing refs/heads/' %
                          (ref.name, value))
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

  def _non_critical_build_check(self, step_name, builds, failures):
    """Update failures based on the current criticality of the builders.

    Args:
      step_name (str): the name for the step.
      builds (list[Build]): Builds to review.
      failures (list[Failure]): Failures to review.

    Returns:
      namedtuple with:
        configs (dict{name:BuilderConfig}): child configs
        failures (list[Failure]): updated failures.
    """
    _non_crit_ret = namedtuple('_non_crit_ret', ['configs', 'failures'])
    with self.m.step.nest(step_name) as presentation:
      self.m.cros_infra_config.force_reload()
      configs = self.m.cros_infra_config.safe_get_builder_configs(
          [b.builder.builder for b in builds])
      failures = self.m.failures.update_non_critical_failures(
          presentation, failures, configs)
      return _non_crit_ret(configs, failures)

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
                            check_critical_step_name=None):
    """Plan, schedule, and run child builders.

    Args:
      run_step_name (str): Name for "run builds" step, or None.
      results_step_name (str): Name for "check build results" step, or None.
      check_critical_step_name (str): Name for "non-critical build check" step,
        or None.

    Returns:
      (BuildsStatus): The current status of the builds.
    """
    with self.m.step.nest(run_step_name or 'run builds') as pres:
      completed_builds, collect_after = self._filter_schedule_wait_builds(
          pres, self._bisect_builder_child_specs())

    check_result = self._collect_and_check_build_results(
        completed_builds, results_step_name=results_step_name,
        check_critical_step_name=check_critical_step_name)

    self._builds_status.update(completed_builds, check_result.failures,
                               check_result.configs, collect_after)
    if not self._builds_status.fatal_failures:
      # If we've made it this far, the relevant child builders were successful
      # and we can update the build success manifest ref if it is specified.
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

    # Recheck the BuilderConfigs at HEAD to see if any failed builds are now
    # non-critical.
    return self._non_critical_build_check(
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

  def _filter_schedule_wait_builds(self, parent_step, child_specs):
    """Find the builds we need, filter those already started, run, and collect.

    Most of the heavy lifting is done in get_build_plan.

    Args:
      parent_step (Step): the calling step, used for presentation purposes.
      child_specs (list(ChildSpec)): A list of child specs.

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

    if new_build_requests:
      # Implement sleepy builds for GoB smoothing: crbug.com/1063143
      with self.m.step.nest('schedule new builds'):
        with self.m.buildbucket.with_host(self.m.buildbucket.HOST_PROD):
          for new_build_request in new_build_requests:
            # Request new builds and add to total existing.
            existing_builds += self.m.buildbucket.schedule(
                [new_build_request], url_title_fn=self.m.naming.get_build_title)
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
        self._properties.enable_history)
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
        check_result = self._collect_and_check_build_results(completed_builds)
        self._builds_status.update(completed_builds, check_result.failures,
                                   check_result.configs)
    return self._builds_status
