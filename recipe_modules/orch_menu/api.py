# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API providing a menu for orchestrator steps"""

import collections
import contextlib

from google.protobuf.json_format import MessageToDict
from google.protobuf.json_format import ParseDict

from recipe_engine import recipe_api

from PB.chromiumos.builder_config import BuilderConfig
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipes.chromeos.orchestrator import OrchestratorProperties
from PB.recipe_modules.chromeos.orch_menu.orch_menu import OrchMenuProperties

_manifest_info = collections.namedtuple(
    '_manifest_info', ['name', 'gitiles_commit', 'path', 'url'])


class OrchMenuApi(recipe_api.RecipeApi):
  """A module with steps used by orchestrators.

  Orchestrators do not call other recipe modules directly: they always get there
  via this module, and are a simple sequence of steps.
  """

  # TODO(crbug/1053703): Make the above statement true.

  # TODO(crbug/1098798, crbug/1093916): Migrate the common orchestrator
  # properties to the module, and stop looking at the global properties.
  def __init__(self, properties, glob_props, *args, **kwargs):
    super(OrchMenuApi, self).__init__(*args, **kwargs)
    # TODO(crbug/1098798): Fix the logic for manifest refs.
    self._has_manifest_refs = True
    self._internal_repo_path = None
    self._external_repo_path = None
    self._external_gitiles_commit = None
    # Our properties: OrchMenuProperties ($chromeos/orch_menu).
    # Merge in the global properties.
    if (not MessageToDict(properties.update_manifest_refs) and
        glob_props.HasField('update_manifest_refs')):
      # No manifest refs were given in the module, but the recipe has them.
      properties.update_manifest_refs.start = glob_props.update_manifest_refs.start
      properties.update_manifest_refs.build = glob_props.update_manifest_refs.build
      properties.update_manifest_refs.test = glob_props.update_manifest_refs.test
    properties.stagger_children_seconds = (
        properties.stagger_children_seconds or
        glob_props.stagger_children_seconds)
    self._properties = properties

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
  def gerrit_changes(self):
    return self.m.cros_infra_config.gerrit_changes

  def get_manifest_info(self, external=False):
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
    if external:
      return _manifest_info(
          'manifest', self._external_gitiles_commit, self._external_repo_path,
          self.m.gitiles.repo_url(self._external_gitiles_commit))
    else:
      return _manifest_info('manifest-internal', self.gitiles_commit,
                            self._internal_repo_path,
                            self.m.gitiles.repo_url(self.gitiles_commit))

  @contextlib.contextmanager
  def setup_orchestrator(self, missing_ok=False, test_footers=None):
    """Initial setup steps for the orchestrator.

    This context manager returns with all of the contexts that the orchestrator
    needs to have when it runs, for cleanup to happen properly.

    Args:
      missing_ok (bool): Whether it is OK if no config is found.
      test_footers (str): test Cr-External-Snapshot footer data(values separated
          by newlines), or None.

    Returns:
      BuilderConfig or None, with an active context.
    """
    with self.m.bot_cost.cq_run_cost_context():
      with self.m.step.nest('set up orchestrator') as presentation:
        self._validate_properties()
        config = self.m.cros_infra_config.configure_builder(
            self.m.buildbucket.gitiles_commit,
            self.m.buildbucket.build.input.gerrit_changes)

        self.m.cros_bisect.set_orchestrator_bisect_builder()
        presentation.links['manifest snapshot revision'] = (
            self.m.gitiles.file_url(self.gitiles_commit, 'snapshot.xml'))

        # If updating manifests, clone the internal manifest repo.
        if self._has_manifest_refs:
          self._internal_repo_path = self.clone_repo('internal manifest',
                                                     self.gitiles_commit)

          # Read the Cr-External-Snapshot footer to get ref of external snapshot
          # that corresponds with the internal snapshot.
          test_data = self.m.git_footers.test_api.step_test_data_factory(
              test_footers or 'external-manifest-SHA')
          with self.m.context(cwd=self._internal_repo_path):
            footer_values = self.m.git_footers.from_ref(
                self.gitiles_commit.id, key='Cr-External-Snapshot',
                step_test_data=test_data)

            # Make sure we got exactly one snapshot ref.
            if not footer_values or len(footer_values) != 1:
              raise self.m.step.StepFailure(
                  'expected exactly one Cr-External-Snapshot footer')
            extern_snapshot_id = footer_values[0]

          self._external_gitiles_commit = common_pb2.GitilesCommit(
              host=self.m.cros_source.EXTERNAL_HOST,
              project=self.m.cros_source.EXTERNAL_PROJECT,
              ref=self.gitiles_commit.ref, id=extern_snapshot_id)

          # clone the external manifest repo
          self._external_repo_path = self.clone_repo(
              'external manifest', self._external_gitiles_commit)

        if not config and not missing_ok:
          raise self.m.step.StepFailure('Missing configuration for {}'.format(
              self.m.buildbucket.builder_name))

      # Yield while inside of the bot_cost.cq_run_cost_context.
      yield config

  def _validate_properties(self):
    """Validate the orchestrator properties.

    Raises:
      StepFailure on errors.
    """
    # The only property we need to validate is update_manifest_refs, and we want
    # to validate all of them.
    for ref, value in self._properties.update_manifest_refs.ListFields():
      if not value.startswith('refs/heads/'):
        raise self.m.step.StepFailure('%s ref %s is missing refs/heads/' %
                                      (ref.name, value))
      self._has_manifest_refs = True

  def clone_repo(self, name, commit):
    """Clone a repo into a temporary directory.

    Args:
      name (str): Display name for the repo.
      commit (GitilesCommit): The commit to clone (and fetch).

    Returns:
      (Path) path of the repo.
    """
    path = self.m.path.mkdtemp()
    url = self.m.gitiles.repo_url(commit)
    with self.m.step.nest('clone %s repo' % name), self.m.context(cwd=path):
      self.m.git.clone(url, timeout_sec=60 * 60)
      if commit.id:
        self.m.git.fetch_ref(url, commit.id, timeout_sec=60 * 60)
    return path

  def push_manifest_refs(self, ref):
    """Update the remote ref (if any).

    If |ref| evaluates to False, do nothing.

    Args:
      ref (str): Ref to push to (possibly empty) or None
    """
    if ref:
      for external in False, True:
        manifest = self.get_manifest_info(external)
        with self.m.step.nest('update %s ref %s' % (manifest.name, ref)), \
            self.m.context(cwd=manifest.path):
          self.m.git.push(manifest.url,
                          "%s:%s" % (manifest.gitiles_commit.id, ref))

  def wait_for_inflight_orchestrator(self):
    """If there is an inflight orchestrator, wait for it."""

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

  def assert_changes_submittable(self):
    """Verify that any changes are submittable."""
    if self.gerrit_changes:
      self.m.gerrit.assert_changes_submittable(self.gerrit_changes)

  def plan_and_run_children(self, enable_history=False, step_name=None):
    """Plan, schedule, and run child builders.

    Args:
      enable_history (bool): Whether history is enabled.
      step_name (str): Name for step, or None.

    Returns:
      (list[Build]): completed builds.
    """
    with self.m.step.nest(step_name or 'run builds') as presentation:
      child_builders = self.m.cros_bisect.get_test_child_builders()
      child_specs = [
          BuilderConfig.Orchestrator.ChildSpec(
              name=cb,
              collect_handling=BuilderConfig.Orchestrator.ChildSpec.COLLECT,
          ) for cb in child_builders
      ] if child_builders else self.config.orchestrator.child_specs
      return self.filter_schedule_wait_builds(presentation, child_specs,
                                              enable_history)

  def filter_schedule_wait_builds(self, parent_step, child_specs,
                                  enable_history):
    """Find the builds we need, filter those already started, run, and collect.

    Most of the heavy lifting is done in get_build_plan.

    Args:
      parent_step (Step): the calling step, to be used for presentation purposes.
      child_specs (list(ChildSpec)): A list of child specs.
      enable_history (bool): Enables history lookup in cq orchestrator.

    Returns: A list of build_pb2.Build objects with build results.
    """
    completed_builds, existing_builds, new_build_requests = (
        self.m.build_plan.get_build_plan(child_specs=child_specs,
                                         enable_history=enable_history,
                                         gerrit_changes=self.gerrit_changes,
                                         snapshot=self.gitiles_commit))
    parent_step.presentation.step_text = ('{} new, {} recycled'.format(
        len(new_build_requests),
        len(completed_builds) + len(existing_builds)))

    if new_build_requests:
      # Implement sleepy builds for GoB smoothing: crbug.com/1063143
      with self.m.step.nest('schedule new builds') as pres:
        with self.m.buildbucket.with_host(self.m.buildbucket.HOST_PROD):
          for new_build_request in new_build_requests:
            # request new builds and add to total existing.
            existing_builds += self.m.buildbucket.schedule(
                [new_build_request], url_title_fn=self.m.naming.get_build_title)
            if self._properties.stagger_children_seconds:
              self.m.time.sleep(self._properties.stagger_children_seconds)

    child_specs_dict = {cs.name: cs for cs in child_specs}
    child_targets_dict = {cs.name.rsplit('-', 1)[0]: cs for cs in child_specs}
    collect_builds = [
        b for b in existing_builds
        if self.should_collect(b, child_specs_dict, child_targets_dict)
    ]

    # collect all existing builds, add to completed builds
    fields = self.m.buildbucket.DEFAULT_FIELDS | {'tags'}
    try:
      completed_builds += self.m.buildbucket.collect_builds(
          [b.id for b in collect_builds], timeout=60 * 60 * 36,
          step_name='collect', url_title_fn=self.m.naming.get_build_title,
          fields=fields).values()
    except self.m.step.StepFailure:
      completed_builds += self.m.buildbucket.get_multi(
          [b.id for b in collect_builds], step_name='get',
          url_title_fn=self.m.naming.get_build_title, fields=fields).values()

    return completed_builds

  def should_collect(self, build, child_specs_dict, child_targets_dict):
    """Returns whether the orchestrator should collect the build.

    Args:
      build (build_pb2.Build): the build to check whether to collect.
      child_specs_dict (dict): mapping of builder name to ChildSpec.
      child_targets_dict (dict): fuzzy mapping of builder target to to ChildSpec.
        Fuzzy in the sense that it just chops off from the last '-' to the end
        of the string. Intended to pick up the *-snapshot cases. See more below.

    Returns: A bool whether to collect the build.
    """
    builder_name = build.builder.builder
    child_spec = child_specs_dict.get(builder_name)
    if not child_spec:
      # Missed lookup, the existing build name was not a name in child_specs.
      # The usual case would be existing build has a *-snapshot name but the
      # orchestrator's child has a *-postsubmit name.
      # TODO(crbug/991996): Refactor: use something other than string manip.
      child_spec = child_targets_dict.get(builder_name.rsplit('-', 1)[0])
    if not child_spec:
      # Missed lookup even after fallback for *-snapshot.
      return True
    return (child_spec.collect_handling !=
            BuilderConfig.Orchestrator.ChildSpec.NO_COLLECT)

  def schedule_wait_build(self, builder, await_completion=False,
                          properties=None, step_name=None, timeout_sec=None):
    """Schedule a builder, and optionally await completion.

    Args:
      builder (str): The name of the builder: one of project/bucket/builder,
        bucket/builder, or builder.
      await_completion (bool): Wether to await completion.
      properties (dict): Dictionary of input properties for the builder.
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
      # gitiles_commit and gerrit_changes that we are using may have derived from
      # our builder config, rather than buildbucket properties.  Pass the actual
      # answers to schedule_request.
      props = self.m.cros_infra_config.props_for_child_build
      props.update(properties or {})
      tags = self.m.cros_tags.make_schedule_tags(self.gitiles_commit)
      req = self.m.buildbucket.schedule_request(
          gitiles_commit=self.gitiles_commit, project=project, bucket=bucket,
          builder=builder, gerrit_changes=self.gerrit_changes, critical=True,
          properties=props, tags=tags)
      title_fn = self.m.naming.get_build_title
      [build] = self.m.buildbucket.schedule([req], url_title_fn=title_fn)
      url = self.m.buildbucket.build_url(build_id=build.id)
      pres.presentation.links[title_fn(build)] = url

      # Are we supposed to wait?
      if await_completion:
        fields = self.m.buildbucket.DEFAULT_FIELDS | {'tags'}
        try:
          [build] = self.m.buildbucket.collect_builds([build.id],
                                                      timeout=timeout_sec,
                                                      step_name='collect',
                                                      url_title_fn=title_fn,
                                                      fields=fields).values()
        except self.m.step.StepFailure:
          [build] = self.m.buildbucket.get_multi([build.id], step_name='get',
                                                 url_title_fn=title_fn,
                                                 fields=fields).values()

      return build
