# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

from PB.chromiumos.builder_config import BuilderConfig

from recipe_engine import recipe_api
from collections import defaultdict
from datetime import datetime

EXTERNAL_REVIEW_HOST = 'chromium-review.googlesource.com'


class BuildPlanApi(recipe_api.RecipeApi):
  """A module to plan the builds to be launched."""

  def __init__(self, properties, *args, **kwargs):
    super(BuildPlanApi, self).__init__(*args, **kwargs)
    self._properties = properties

  # A Git footer that can be included in commit messages to tell the cq run to not
  # recycled builds for that builder.
  DISALLOW_RECYCLED_BUILDS_FOOTER = 'Disallow-Recycled-Builds'

  # A Git footer that can be included in commit messages to tell the CQ run to
  # enable an experiment.  This name was chosen to avoid conflicting with a
  # similar feature being added to LUCI CQ.
  CROS_EXPERIMENTS_FOOTER = 'Cros-Experiments'

  def get_build_plan(self, child_specs, enable_history, gerrit_changes,
                     internal_snapshot, external_snapshot):
    """Return a three-tuple of builds, completed, existing, and needed.

    This will be split into specialized functions for cq, release, others.

    Args:
      child_specs (list[ChildSpec]): List of child specs of the child
        builders.
      enable_history (bool): Enables history lookup in the orchestrator.
      gerrit_changes list(GerritChange): List of patches in the order that they
        can be cherry-picked.
      internal_snapshot (GitilesCommit): gitiles_commit of the internal manifest
        to be supplied to child builds syncing to the internal manifest.
      external_snapshot (GitilesCommit): gitiles_commit of the public manifest
        to be supplied to child builds syncing to the external manifest.

    Returns:
      A tuple of three lists:
        A list of Build objects of successful builds with refreshed criticality.
        A list of -snapshot builds we don't need to schedule and can join.
        A list of ScheduleBuildRequests that have to be scheduled.
    """
    filter_log = []
    completed_builds, snapshot_builds, new_build_requests = [], [], []
    is_retry = False

    builder_configs = [
        self.m.cros_infra_config.get_builder_config(b.name) for b in child_specs
    ]
    necessary_builders = [b.id.name for b in builder_configs]
    if gerrit_changes and not self._properties.disable_build_plan_pruning:
      necessary_builders = self.m.cros_relevance.get_necessary_builders(
          builder_configs, gerrit_changes, internal_snapshot, test_builder_ids=[
              b.id for b in builder_configs if 'pointless' not in b.id.name
          ])
    # Handle forced relevancy.
    forced_relevant = self.m.cros_relevance.check_force_relevance_footer(
        gerrit_changes, builder_configs)
    necessary_builders = list(set(necessary_builders) | set(forced_relevant))
    any_public_changes = any(
        c.host == EXTERNAL_REVIEW_HOST for c in gerrit_changes)

    slim_eligible_run = any(x.endswith('slim-cq') for x in necessary_builders)

    forced_rebuilds = set()
    if enable_history:
      if gerrit_changes:
        forced_rebuilds = self.get_forced_rebuilds(gerrit_changes)
        with self.m.step.nest('get build history') as presentation:
          orch_config = self.m.cros_infra_config.config_or_default
          is_retry = (
              orch_config.id.type == BuilderConfig.Id.CQ and
              self.m.cros_history.is_retry())
          completed_builds = self.get_completed_builds(child_specs,
                                                       forced_rebuilds)
          presentation.step_text = ('found {} build{} to recycle'.format(
              len(completed_builds), '' if len(completed_builds) == 1 else 's'))

      # By filtering to the names of the builders in child_specs,
      # the *-snapshot builders will be ignored. See https://crbug.com/1040593
      # for details on why we want the actual *-postsubmit builders to run.
      snapshot_builds = self.m.cros_history.get_snapshot_builds(
          internal_snapshot, [cs.name for cs in child_specs],
          [common_pb2.SUCCESS, common_pb2.SCHEDULED, common_pb2.STARTED],
          patches=gerrit_changes)

    # Find number of builds, make set of builders, prioritize and log.
    initial_found_builds = len(snapshot_builds)
    snapshot_builds = self.prioritize_builds(snapshot_builds)
    filter_log.append(
        'from {} -> {} joinable after dedup and prioritization'.format(
            initial_found_builds, len(snapshot_builds)))

    completed_builders = [build.builder.builder for build in completed_builds]
    snapshot_build_targets = \
        self.m.cros_infra_config.build_target_dict(snapshot_builds)

    filtered_snapshot_builds = []

    count_skip_for_source_rules = 0
    count_skip_since_already_passed = 0
    count_skip_wait_on_other_run = 0
    count_skip_noncritical_on_rerun = 0
    count_scheduled_slim_builds = 0
    count_skip_public_builders = 0

    with self.m.step.nest('filter builds') as presentation:
      child_exps = self.m.cros_infra_config.experiments_for_child_build
      footer_exps = self.m.git_footers.get_footer_values(
          gerrit_changes, self.CROS_EXPERIMENTS_FOOTER,
          step_test_data=self.m.git_footers.test_api.step_test_data_factory(''))
      child_exps.update({x: True for x in footer_exps})
      # Check if CQ looks experiment is enabled
      if 'chromeos.cros_infra_config.cq_looks' in child_exps:
        # TODO(b/211620738): Also use Gitiles footer to allow lookback-only or
        # wait-only CQ looks behaviors.
        cq_looks_enabled = True
        snapshot_ids = set()
        filter_log.append('CQ looks experiment enabled')
      else:
        cq_looks_enabled = False
        filter_log.append('CQ looks experiment not enabled')

      for child_spec in child_specs:
        # Get the builder variant in the build plan.
        if child_spec.name in necessary_builders:
          child_builder_name = child_spec.name
        elif self.get_slim_builder_name(child_spec.name) in necessary_builders:
          child_builder_name = self.get_slim_builder_name(child_spec.name)
          standard_builder_name = child_spec.name
        else:
          filter_log.append('{} build is not needed for changes'.format(
              child_spec.name))
          count_skip_for_source_rules += 1
          continue

        child_builder_config = self.m.cros_infra_config.get_builder_config(
            child_builder_name)
        critical = child_builder_config.general.critical.value
        force_rebuild = child_builder_name in forced_rebuilds or 'all' in forced_rebuilds
        force_relevant = child_builder_name in forced_relevant

        # Public builders can only apply changes to the chromium host.
        # If all CLs are in chrome-internal then we know the build will not be
        # relevant.
        if gerrit_changes and not any_public_changes and (
            child_builder_config.general.manifest ==
            BuilderConfig.General.PUBLIC) and not force_relevant:
          count_skip_public_builders += 1
          filter_log.append(
              '{} is a public builder and there are no changes to the external host'
              .format(child_spec.name))
          continue

        # Now we have a list of build names such as ['buddy-postsubmit', ...]
        # whereas snapshot_builds and completed_builds might be postfixed
        # with -snapshot. Use this to filter out.
        # TODO(crbug/991996): Refactor: use something other than string manip.
        # e.g. amd64-generic-asan-cq -> amd64-generic-asan
        child_builder_spec = child_builder_name[:child_builder_name.rfind('-')]
        # No need to retry previously-passed builds.
        if child_builder_name in completed_builders:
          filter_log.append('{} already passed'.format(child_builder_spec))
          count_skip_since_already_passed += 1
          continue

        # Do not retry slim builds if an equivalent standard build passed.
        if child_builder_name.endswith(
            'slim-cq') and standard_builder_name in completed_builders:
          filter_log.append('{} already passed'.format(standard_builder_name))
          count_skip_since_already_passed += 1
          continue

        # We've already found an existing build, we'll just wait on it later.
        if child_builder_spec in snapshot_build_targets:
          snapshot_build = snapshot_build_targets[child_builder_spec]
          snapshot_build.critical = common_pb2.YES if critical else common_pb2.NO
          filtered_snapshot_builds.append(snapshot_build)
          filter_log.append(
              '{} exists, will join on it'.format(child_builder_spec))
          count_skip_wait_on_other_run += 1
          continue

        # Don't retry non-critical builds unless recycling is disabled.
        if is_retry and not (critical or force_rebuild):
          filter_log.append('{} is non-critical and this is a CQ rerun'.format(
              child_builder_name))
          count_skip_noncritical_on_rerun += 1
          continue

        child_build_snapshot = internal_snapshot
        if (child_builder_config.general.manifest ==
            BuilderConfig.General.PUBLIC):
          child_build_snapshot = external_snapshot

        # If CQ Looks is enabled, collect a set of snapshot ids that will be
        # used in this build plan so we can validate they are green snapshots.
        # TODO(b/211620738): Refine to consider history of snapshots within
        # lookback window.
        if cq_looks_enabled:
          filter_log.append('CQ looks: found snapshot {} for build {}'.format(
              child_build_snapshot.id, child_spec.name))
          snapshot_ids.add(child_build_snapshot.id)

        tags = self.m.cros_tags.make_schedule_tags(child_build_snapshot)

        # Technically per current approaches a bisecting orchestrator doing hw
        # test bisection should find all builds already completed or in flight
        # as *-snapshot builds. If it does need to schedule such a build, those
        # builders run in the postsubmit bucket.
        bucket = self.m.buildbucket.build.builder.bucket
        if bucket == 'bisect':
          bucket = 'postsubmit'
        parent_run_id = None
        if (child_spec.collect_handling !=
            BuilderConfig.Orchestrator.ChildSpec.NO_COLLECT):
          # If collect handling not set to NO_COLLECT, the child will be
          # terminated if the orchestrator dies and the child is not finished.
          parent_run_id = self.m.swarming.task_id

        # Build the properties for the child.
        properties = self.m.cq.props_for_child_build
        properties.update(self.m.cros_infra_config.props_for_child_build)
        if force_relevant:
          properties.update({'force_relevant_build': True})

        if child_builder_name.endswith('-slim-cq'):
          count_scheduled_slim_builds += 1

        new_build_requests.append(
            self.m.buildbucket.schedule_request(
                gitiles_commit=child_build_snapshot, inherit_buildsets=False,
                builder=child_builder_name, bucket=bucket,
                gerrit_changes=gerrit_changes, critical=critical, tags=tags,
                properties=properties, experiments=child_exps,
                swarming_parent_run_id=parent_run_id))

      presentation.logs['filter log'] = filter_log

      # TODO(b/211620738): Add 2 additional queries to change snapshot based
      # historic greenness for unfinished or failed snapshots.
      if cq_looks_enabled:
        with self.m.step.nest('CQ looks'):
          if snapshot_ids:
            self.m.cq_looks.get_unfinished_or_failed_snapshot_ids(snapshot_ids)

      # Don't include irrelevant builder configs or snapshot builds in this
      # count for display, as they're mentioned in steps above.
      count_total_filtered_builds = (
          count_skip_for_source_rules + count_skip_since_already_passed +
          count_skip_wait_on_other_run + count_skip_noncritical_on_rerun +
          count_skip_public_builders)
      presentation.step_text = ('need {} new build{} (filtered {})'.format(
          len(new_build_requests), '' if len(new_build_requests) == 1 else 's',
          count_total_filtered_builds))

      self.m.easy.set_properties_step(
          build_plan_skip_for_source_rules=count_skip_for_source_rules,
          build_plan_skip_for_already_passed=count_skip_since_already_passed,
          build_plan_skip_for_wait_on_other_run=count_skip_wait_on_other_run,
          build_plan_skip_for_noncritical_on_rerun=(
              count_skip_noncritical_on_rerun),
          build_plan_new_build_requests=len(new_build_requests),
          count_scheduled_slim_builds=count_scheduled_slim_builds,
          slim_eligible_run=slim_eligible_run,
          count_skip_public_builders=count_skip_public_builders)

    return completed_builds, filtered_snapshot_builds, new_build_requests

  def get_completed_builds(self, child_specs, forced_rebuilds):
    """Get the list of previously passed child builds with criticality refreshed.

    Args:
      api (RecipeApi): See RunSteps documentation.
      child_specs list(ChildSpec): List of child specs of cq-orchestrator.
      forced_rebuilds list(str): List of builder names that cannot be reused.

    Returns:
      A list of build_pb2.Build objects corresponding to the
      latest successful child builds with the same patches as the current
      cq orchestrator with refreshed critical values.
    """
    with self.m.step.nest("get completed builds") as presentation:
      completed_builds = []
      passed_builds = self.m.cros_history.get_passed_builds()
      count_broken_before_rebuilds = 0

      skip_log = []
      for build in passed_builds:
        # Filter out non-child builds like vm_test, dry run orchestrator or
        # hw_tests in the future.
        child_builders = [cs.name for cs in child_specs] + [
            self.get_slim_builder_name(cs.name) for cs in child_specs
        ]
        if build.builder.builder not in child_builders:  #pragma: no cover
          continue

        if build.builder.builder in forced_rebuilds or 'all' in forced_rebuilds:
          skip_log.append(
              '{} is skipped because recycling was disabled for this builder.'
              .format(build.builder.builder))
          continue

        builder_config = self.m.cros_infra_config.get_builder_config(
            build.builder.builder)
        # If the build ran before a known bug was fixed, don't reuse it.
        if build.start_time.seconds < builder_config.general.broken_before.seconds:
          count_broken_before_rebuilds += 1
          skip_log.append(
              '{} is skipped because it was broken till {}UTC'.format(
                  build.builder.builder,
                  datetime.utcfromtimestamp(
                      builder_config.general.broken_before.seconds)))
          continue

        # Refresh the criticality of the builders.
        build.critical = (
            common_pb2.YES
            if builder_config.general.critical.value else common_pb2.NO)
        completed_builds.append(build)

      presentation.logs['skip log'] = skip_log
      presentation.properties[
          'count_broken_before_rebuilds'] = count_broken_before_rebuilds
      return completed_builds

  def prioritize_builds(self, builds):
    """Takes a list of builds and dedups, choosing a best build, dropping others.

    See build_orderer for the sort order. This is most useful if you have
    multiple, identical, builds and you want to choose a single one from each
    builder type to carry forward.

    Args:
      builds ([build_pb2.Build]): Builds to dedupe and sort.

    Returns: A list of build_pb2.Build objects, deduped and prioritized.
    """

    def build_orderer(b1, b2):
      if b1.status == common_pb2.SUCCESS and b2.status != common_pb2.SUCCESS:
        return -1
      elif b2.status == common_pb2.SUCCESS and b1.status != common_pb2.SUCCESS:
        return 1
      else:
        # otherwise get the earliest created, which will be reasonable for
        # running builds and scheduled builds if scheduling is fair.
        return int(b1.create_time.seconds - b2.create_time.seconds)

    # add all of them to dict: build_target -> build proto
    build_map = defaultdict(list)
    for b in builds:
      bt = self.m.cros_infra_config.get_build_target_name(b)
      if bt:
        build_map[bt].append(b)

    best_builds_list = []
    for _, build_list in build_map.items():
      best_build = sorted(build_list,
                          cmp=build_orderer)[0]  # [0] most preferable
      best_builds_list.append(best_build)

    # return reduced list
    return best_builds_list

  def get_forced_rebuilds(self, gerrit_changes):
    """Gets a list of builders whose builds should not be reused.

    Compiles a list of all builders whose builds should not be reused as
    indicated by the Gerrit changes' commit messages. For multiple changes, the
    union of these list is returned.

    Args:
      gerrit_changes ([common_pb2.GerritChange]): Gerrit changes applied to this
        run.

    Returns:
      forced_rebuilds (set(str)): A set of builder names or 'all' if no builds can be
        reused.
    """
    with self.m.step.nest('check disallow recycled builds') as pres:
      forced_rebuilds = self.m.git_footers.get_footer_values(
          gerrit_changes, self.DISALLOW_RECYCLED_BUILDS_FOOTER)

      if not forced_rebuilds:
        pres.step_text = 'no forced rebuilds'
        return forced_rebuilds

      pres.logs['found footer values'] = 'found value(s): %s' % ','.join(
          list(forced_rebuilds))

      if 'all' in forced_rebuilds:
        pres.step_text = 'rebuild all targets'
        return {'all'}

      if 'test-failures' in forced_rebuilds:
        test_failure_builders = self.m.cros_history.get_test_failure_builders()
        forced_rebuilds.remove('test-failures')
        forced_rebuilds.update(test_failure_builders)

      pres.logs['forced rebuilds'] = forced_rebuilds
      pres.step_text = 'force rebuild %s target(s)' % len(forced_rebuilds)
      return forced_rebuilds

  def get_slim_builder_name(self, builder_name):
    """Returns to the name of the slim variant of the builder.

    Args:
      builder_name (str): The name of the builder for which to get the slim
        builder variant name.

    Returns:
       A string of the slim builder name.
    """
    builder_spec, env_suffix = builder_name.rsplit('-', 1)
    return builder_spec + '-slim-' + env_suffix
