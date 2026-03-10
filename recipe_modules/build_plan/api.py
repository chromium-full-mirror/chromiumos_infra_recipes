# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Functions related to build planning."""

from typing import List, Optional, Set, Tuple

from google.protobuf import json_format

from PB.chromite.api import relevancy as relevancy_pb2
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto \
  import builds_service as builds_service_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as bb_common_pb2
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.go.chromium.org.luci.buildbucket.proto.common import GitilesCommit
from PB.recipe_modules.chromeos.cros_source.cros_source import GitStrategy
from PB.recipe_modules.chromeos.looks_for_green.looks_for_green import LooksForGreenStatus

from RECIPE_MODULES.chromeos.src_state.common import ManifestProject

from recipe_engine import recipe_api

EXTERNAL_REVIEW_HOST = 'chromium-review.googlesource.com'

# Timeout for calls to the relevancy service.
# Timeout of 5 minutes should impact less than 1% of runs (b/381930071).
RELEVANCY_SERVICE_TIMEOUT_SECONDS = 5 * 60


class BuildPlanApi(recipe_api.RecipeApi):
  """A module to plan the builds to be launched."""

  def __init__(self, properties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._properties = properties
    self._additional_chrome_pupr_builders = (
        properties.additional_chrome_pupr_builders or [])

  # A Git footer that can be included in commit messages to tell the cq run to not
  # recycled builds for that builder.
  DISALLOW_RECYCLED_BUILDS_FOOTER = 'Disallow-Recycled-Builds'

  # A Git footer that can be included in commit messages to tell the CQ run to
  # enable an experiment.  This name was chosen to avoid conflicting with a
  # similar feature being added to LUCI CQ.
  CROS_EXPERIMENTS_FOOTER = 'Cros-Experiments'

  @property
  def additional_chrome_pupr_builders(self):
    return self._additional_chrome_pupr_builders

  def _check_project_outside_manifest(self, gerrit_changes):
    """Check if gerrit_changes contains any project outside the manifest.

    Args:
      gerrit_changes list(GerritChange): List of patches in the order that they
        can be cherry-picked.

    Raise:
          StepFailure if any of the gerrit_changes contains a project outside
          manifest.
    """
    excluded_project = ['chromeos/manifest', 'chromeos/manifest-internal']
    with self.m.step.nest('check for projects outside manifest'):
      with self.m.context(cwd=self.m.src_state.build_manifest.path):
        runner = self.m.future_utils.create_parallel_runner()
        for gc in gerrit_changes:
          runner.run_function_async(
              lambda project, _: self.m.repo.project_exists(project),
              gc.project)
        responses = runner.wait_for_and_get_responses()
        not_in_manifest = [
            project.req
            for project in responses
            if not project.resp and not project.req in excluded_project
        ]
        if not_in_manifest:
          raise recipe_api.StepFailure(
              'Detected at least one project that is not in the manifest! '
              'Please add following projects {} to manifest file and retry.'
              .format(not_in_manifest))

  def get_relevant_builders(self, builders: List[BuilderConfig],
                            gerrit_changes: List[GerritChange]):
    """Returns builders deemed relevant by the RelevancyService."""
    try:
      builder_configs = [
          self.m.cros_infra_config.get_builder_config(b) for b in builders
      ]
      req = relevancy_pb2.GetRelevantBuildTargetsRequest(
          build_targets=[bc.build_target for bc in builder_configs])

      patch_sets = self.m.gerrit.fetch_patch_sets(gerrit_changes,
                                                  include_files=True)
      affected_paths = self.m.cros_relevance.get_affected_paths(patch_sets)
      for p in affected_paths:
        path = req.affected_paths.add()
        path.path = p

      resp = self.m.cros_build_api.RelevancyService.GetRelevantBuildTargets(
          req, timeout=RELEVANCY_SERVICE_TIMEOUT_SECONDS)
      relevant_build_targets = [bt.build_target for bt in resp.build_targets]

      # Bazel builders need to be forced relevant for changes to the
      # 'chromiumos/bazel' repo.
      relevant_bazel_builder_configs = []
      if any(gc.project == 'chromiumos/bazel' for gc in gerrit_changes):
        relevant_bazel_builder_configs = [
            bc for bc in builder_configs if '-bazel-' in bc.id.name
        ]

      self.cros_query_relevant_builders = [
          bc.id.name
          for bc in builder_configs
          if bc.build_target in relevant_build_targets or
          bc in relevant_bazel_builder_configs or
          # Builders with an empty build_target should be assumed relevant
          # (e.g. chromite-cq).
          bc.build_target == common_pb2.BuildTarget()
      ]
      return self.cros_query_relevant_builders

    except recipe_api.StepFailure:
      # If there is a failure calling the relevancy service, fallback to
      # scheduling all builders.
      return builders

  def _get_necessary_cq_child_specs(
      self, child_specs: List[BuilderConfig.Orchestrator.ChildSpec],
      necessary_builders: List[str]
  ) -> List[BuilderConfig.Orchestrator.ChildSpec]:
    """Returns a list of all necessary child_specs for the CQ run.

    The cq-orchestrator can schedule more of less child builders than are
    in its builder config. This function creates child specs for non-default
    child builds such as slim-cq builds or snapshot-only builds which were
    forced relevant.

    This function also filters out child specs for builders which were deemed
    irrelevant by the build planner.

    Args:
      child_specs: The default child_specs for the CQ orchestrator build as
          specified in the builder config.
      necessary_builders: A list of builders deemed necessary by the
          build_planner and via footer.

    Returns:
      necessary_child_specs: A list of the necessary child_specs to schedule.
    """

    necessary_child_specs = []
    for c in child_specs:
      if c.name in necessary_builders:
        necessary_child_specs.append(c)
      elif self.get_slim_builder_name(c.name) in necessary_builders:
        slim_cq_child_spec = BuilderConfig.Orchestrator.ChildSpec()
        slim_cq_child_spec.CopyFrom(c)
        slim_cq_child_spec.name = self.get_slim_builder_name(c.name)
        necessary_child_specs.append(slim_cq_child_spec)

    # Create child specs for non-default builders which were forced relevant.
    necessary_child_spec_names = {c.name for c in necessary_child_specs}
    for b in necessary_builders:
      if b not in necessary_child_spec_names:
        # Builders returned from cros_relevance.check_force_relevance_footer
        # are guarenteed to exist, so we should not worry about failing here.
        config = self.m.cros_infra_config.get_builder_config(b)
        necessary_child_specs.append(
            BuilderConfig.Orchestrator.ChildSpec(name=b,
                                                 bucket=config.id.bucket))
    return necessary_child_specs

  def _get_necessary_chrome_child_specs(
      self, gerrit_changes: List[Optional[GerritChange]],
      builders: List[Optional[str]], completed_builders: List[Optional[str]]
  ) -> List[Optional[BuilderConfig.Orchestrator.ChildSpec]]:
    """Returns additional ChildSpecs to schedule for chrome uprev changes.

    Args:
      gerrit_changes: The changes under test. Used to determine if the CQ run is
          testing a chrome uprev.
      builders: A list of builders to consider scheduling.
      completed_builders: A list of builders that already completed.
    """
    necessary_chrome_child_specs = []
    chrome_log = []
    with self.m.step.nest(
        'filter additional chrome pupr builds') as presentation:
      if not (len(gerrit_changes) == 1 and
              self.m.chrome.is_chrome_pupr_atomic_uprev(gerrit_changes[0])):
        presentation.step_text = 'no additional builds needed'
        return necessary_chrome_child_specs

      for builder in sorted(builders):
        builder_config = self.m.cros_infra_config.get_builder_config(builder)

        # Only schedule builds for critical CQ builders.
        if not builder_config.general.critical.value:
          chrome_log.append(f'{builder} not needed because it is non-critical')
          continue
        # No need to retry previously-passed builds.
        if builder in completed_builders:
          chrome_log.append(f'{builder} already passed')
          continue
        # Do not schedule builds that do not use prebuilts.
        if not builder_config.artifacts.prebuilts_gs_bucket:
          chrome_log.append(
              f'{builder} not needed because it does not use prebuilts')
          continue
        chrome_log.append(f'{builder} needs to be scheduled')
        necessary_chrome_child_specs.append(
            BuilderConfig.Orchestrator.ChildSpec(
                name=builder, bucket=builder_config.id.bucket,
                collect_handling=BuilderConfig.Orchestrator.ChildSpec.NO_COLLECT
            ))

      presentation.logs['additional builds'] = sorted(chrome_log)
      return necessary_chrome_child_specs

  def get_build_plan(
      self, child_specs: List[BuilderConfig.Orchestrator.ChildSpec],
      enable_history: bool, gerrit_changes: List[GerritChange],
      internal_snapshot: GitilesCommit, external_snapshot: GitilesCommit
  ) -> Tuple[List[build_pb2.Build],
             List[builds_service_pb2.ScheduleBuildRequest]]:
    """Return a two-tuple of completed and needed builds.

    This will be split into specialized functions for cq, release, others.

    Args:
      child_specs: List of child specs of the child builders.
      enable_history: Enables history lookup in the orchestrator.
      gerrit_changes: List of patches applied to the build.
      internal_snapshot: The GitilesCommit of the internal manifest passed to
          child builds syncing to the internal manifest.
      external_snapshot: The GitilesCommit of the public manifest passed to
          child builds syncing to the external manifest.

    Returns:
      A tuple of two lists:
        A list of Build objects of successful builds with refreshed criticality.
        A list of ScheduleBuildRequests that have to be scheduled.
    """
    filter_log = []
    completed_builds, new_build_requests = [], []
    is_retry = False

    count_skip_for_source_rules = 0
    count_skip_since_already_passed = 0
    count_skip_noncritical_on_rerun = 0

    builder_configs = [
        self.m.cros_infra_config.get_builder_config(b.name) for b in child_specs
    ]
    necessary_builders = [b.id.name for b in builder_configs]
    irrelevant_builders = set()
    necessary_child_specs = child_specs
    forced_rebuilds = set()
    forced_relevant = []

    necessary_chrome_child_specs = []

    if gerrit_changes:
      any_public_changes = any(
          c.host == EXTERNAL_REVIEW_HOST for c in gerrit_changes)
      if not self._properties.disable_build_plan_pruning:
        # The build planner cannot run on CLs for repos that are not defined in
        # the manifest.
        self._check_project_outside_manifest(gerrit_changes)

        # Run the build plan generator.
        builders_tuple = self.m.cros_relevance.run_build_planner(
            builder_configs, gerrit_changes, internal_snapshot)
        necessary_builders = builders_tuple.necessary
        irrelevant_builders = set(builders_tuple.run_when_rules_skipped +
                                  builders_tuple.global_irrelevance_skipped)

        with self.m.step.nest('filter builds using cros query') as pres:
          relevant_builders = self.get_relevant_builders(
              necessary_builders, gerrit_changes)
          # Add logging about decisions.
          skipped_builders = sorted(
              [b for b in necessary_builders if b not in relevant_builders])
          pres.step_text = f'filtered out {len(skipped_builders)} builders'
          pres.logs['skipped builders'] = skipped_builders
          pres.properties['cros_query_skipped_builders'] = skipped_builders

          # Update our lists.
          necessary_builders = relevant_builders
          irrelevant_builders.update(skipped_builders)

        # Public builders can only apply changes to the chromium host.
        # If all CLs are in chrome-internal then we know the build will not be
        # relevant.
        for b in necessary_builders:
          child_builder_config = self.m.cros_infra_config.get_builder_config(b)
          if (child_builder_config.general.manifest
              == BuilderConfig.General.PUBLIC) and not any_public_changes:
            irrelevant_builders.add(b)
        necessary_builders = list(set(necessary_builders) - irrelevant_builders)

      # Handle forced relevancy.
      forced_relevant = self.m.cros_relevance.check_force_relevance_footer(
          gerrit_changes, builder_configs)
      necessary_builders = list(set(necessary_builders) | set(forced_relevant))
      # Given the build plan and forced relevancy results, get a list of all
      # necessary child specs. This includes creating child specs for
      # forced relevant and slim cq builds.
      necessary_child_specs = self._get_necessary_cq_child_specs(
          list(child_specs), necessary_builders)

      # Log info about irrelevant builds.
      necessary_child_spec_names = {c.name for c in necessary_child_specs}
      for c in child_specs:
        if c.name not in necessary_child_spec_names and self.get_slim_builder_name(
            c.name) not in necessary_child_spec_names:
          filter_log.append(f'{c.name} build is not needed for changes')
          count_skip_for_source_rules += 1

      if enable_history:
        forced_rebuilds = self.get_forced_rebuilds(gerrit_changes)
        with self.m.step.nest('get build history') as presentation:
          orch_config = self.m.cros_infra_config.config_or_default
          is_retry = (
              orch_config.id.type == BuilderConfig.Id.CQ and
              self.m.cros_history.is_retry)
          completed_builds = self.get_completed_builds(child_specs,
                                                       forced_rebuilds)
          presentation.step_text = ('found {} build{} to recycle'.format(
              len(completed_builds), '' if len(completed_builds) == 1 else 's'))

      completed_builders = [build.builder.builder for build in completed_builds]
      with self.m.step.nest('filter builds') as presentation:
        filtered_child_specs = []
        for child_spec in necessary_child_specs:
          # No need to retry previously-passed builds.
          if child_spec.name in completed_builders:
            filter_log.append(f'{child_spec.name} already passed')
            count_skip_since_already_passed += 1
            continue

          # Do not retry slim builds if an equivalent standard build passed.
          if child_spec.name.endswith('slim-cq'):
            standard_builder_name = child_spec.name.replace('-slim-cq', '-cq')
            if standard_builder_name in completed_builders:
              filter_log.append(f'{standard_builder_name} already passed')
              count_skip_since_already_passed += 1
              continue

          # Don't retry non-critical builds unless recycling is disabled.
          child_builder_config = self.m.cros_infra_config.get_builder_config(
              child_spec.name)
          force_rebuild = child_spec.name in forced_rebuilds or 'all' in forced_rebuilds
          force_relevant = child_spec.name in forced_relevant
          critical = child_builder_config.general.critical.value or force_relevant
          if is_retry and not (critical or force_rebuild):
            filter_log.append(
                f'{child_spec.name} is non-critical and this is a CQ rerun')
            count_skip_noncritical_on_rerun += 1
            continue

          # If we made it this far, we need to schedule the build.
          filtered_child_specs.append(child_spec)

        necessary_child_specs = filtered_child_specs

        presentation.logs['filter log'] = sorted(filter_log)

        # Don't include irrelevant builder configs or snapshot builds in this
        # count for display, as they're mentioned in steps above.
        count_total_filtered_builds = (
            count_skip_for_source_rules + count_skip_since_already_passed +
            count_skip_noncritical_on_rerun)
        presentation.step_text = ('need {} new build{} (filtered {})'.format(
            len(necessary_child_specs),
            '' if len(necessary_child_specs) == 1 else 's',
            count_total_filtered_builds))

      necessary_chrome_child_specs = self._get_necessary_chrome_child_specs(
          gerrit_changes, irrelevant_builders,
          [build.builder.builder for build in completed_builds])

    child_exps = self.m.cros_infra_config.experiments_for_child_build
    footer_exps = self.m.git_footers.get_footer_values(
        gerrit_changes, self.CROS_EXPERIMENTS_FOOTER,
        step_test_data=self.m.git_footers.test_api.step_test_data_factory(''))
    child_exps.update({x: True for x in footer_exps})

    # Only do LFG logic if are any critical or chrome prebuilt builders to
    # schedule.
    lfg_builder_names = []
    for b in necessary_child_specs:
      critical = self.m.cros_infra_config.get_builder_config(
          b.name).general.critical.value
      if (critical or b.name in forced_relevant):
        lfg_builder_names.append(b.name)
    lfg_builder_names += [b.name for b in necessary_chrome_child_specs]

    if lfg_builder_names:
      internal_snapshot, external_snapshot = self._choose_snapshots(
          internal_snapshot, external_snapshot, gerrit_changes,
          self.m.src_state.internal_manifest, lfg_builder_names)


    for child_spec in necessary_child_specs:
      child_builder_config = self.m.cros_infra_config.get_builder_config(
          child_spec.name)
      force_relevant = child_spec.name in forced_relevant
      critical = child_builder_config.general.critical.value or force_relevant

      child_build_snapshot = internal_snapshot
      if (child_builder_config.general.manifest == BuilderConfig.General.PUBLIC
         ):
        child_build_snapshot = external_snapshot

      tags = self.m.cros_tags.make_schedule_tags(child_build_snapshot)
      if not critical and child_spec.name.endswith('-cq'):
        tags.extend(
            self.m.cros_tags.tags(**{'hide-in-gerrit': 'non-critical-builder'}))

      if child_spec.bucket:
        bucket = child_spec.bucket
      elif self.m.led.led_build:
        bucket = self.m.led.shadowed_bucket
      else:
        bucket = self.m.buildbucket.build.builder.bucket
      can_outlive_parent = True
      if (child_spec.collect_handling
          != BuilderConfig.Orchestrator.ChildSpec.NO_COLLECT):
        # If collect handling not set to NO_COLLECT, the child will be
        # terminated if the orchestrator dies and the child is not finished.
        can_outlive_parent = False

      # Build the properties for the child.
      properties = self.m.cv.props_for_child_build
      properties.update(self.m.cros_infra_config.props_for_child_build)
      if force_relevant:
        properties.update({'force_relevant_build': True})

      new_build_requests.append(
          self.m.buildbucket.schedule_request(
              gitiles_commit=child_build_snapshot, inherit_buildsets=False,
              builder=child_spec.name, bucket=bucket,
              gerrit_changes=gerrit_changes, critical=critical, tags=tags,
              properties=properties, experiments=child_exps,
              can_outlive_parent=can_outlive_parent))

    # Schedule additional non-critical builds for chrome PUpr Uprev CLs.
    for child_spec in necessary_chrome_child_specs:
      builder = child_spec.name
      builder_config = self.m.cros_infra_config.get_builder_config(builder)

      child_build_snapshot = internal_snapshot
      if builder_config.general.manifest == BuilderConfig.General.PUBLIC:
        child_build_snapshot = external_snapshot
      tags = self.m.cros_tags.make_schedule_tags(child_build_snapshot)
      tags.extend(
          self.m.cros_tags.tags(
              **{'hide-in-gerrit': 'chrome-additional-builder'}))
      properties = self.m.cv.props_for_child_build
      properties.update(self.m.cros_infra_config.props_for_child_build)

      new_build_requests.append(
          self.m.buildbucket.schedule_request(
              gitiles_commit=child_build_snapshot, builder=builder,
              bucket=child_spec.bucket, gerrit_changes=gerrit_changes,
              critical=False, tags=tags, properties=properties,
              experiments=child_exps))
      self._additional_chrome_pupr_builders.append(builder)

    self.m.easy.set_properties_step(
        build_plan_skip_for_source_rules=count_skip_for_source_rules,
        build_plan_skip_for_already_passed=count_skip_since_already_passed,
        build_plan_skip_for_noncritical_on_rerun=(
            count_skip_noncritical_on_rerun),
        build_plan_new_build_requests=len(new_build_requests),
        slim_eligible_run=any(
            x.endswith('slim-cq') for x in necessary_builders))

    return completed_builds, new_build_requests

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
    with self.m.step.nest('get completed builds') as presentation:
      completed_builds = []
      passed_builds = self.m.cros_history.get_passed_builds()
      count_broken_before_rebuilds = 0

      skip_log = []
      for build in passed_builds:
        # Filter out non-child builds like vm_test, dry run orchestrator or
        # hw_tests in the future.
        builder = build.builder.builder
        with self.m.step.nest(f'checking {builder}') as pres:
          child_builders = [cs.name for cs in child_specs] + [
              self.get_slim_builder_name(cs.name) for cs in child_specs
          ]
          if builder not in child_builders:  #pragma: no cover
            continue

          if builder in forced_rebuilds or 'all' in forced_rebuilds:
            skip_log.append(
                '{} is skipped because recycling was disabled for this builder.'
                .format(build.builder.builder))
            continue

          builder_config = self.m.cros_infra_config.get_builder_config(builder)
          pres.logs['builder_config_json'] = json_format.MessageToJson(
              builder_config)
          broken_until_snapshot = builder_config.general.broken_until
          if broken_until_snapshot:
            # broken_until only works with ToT CQ (ie not LTS).
            if build.input.gitiles_commit.ref not in [
                'refs/heads/snapshot', 'refs/heads/staging-snapshot'
            ]:
              completed_builds.append(build)
              continue
            build_snapshot = build.input.gitiles_commit.id
            is_build_broken = self.m.cros_history.is_build_broken(
                build_snapshot, broken_until_snapshot)
            # If we were not able to find an annealing build for one of the
            # snapshots, is_build_broken will return None.
            # TODO(b/338615036): For now, do not recycle the build in this case.
            if is_build_broken or is_build_broken is None:
              count_broken_before_rebuilds += 1
              skip_log.append(
                  '{} is skipped because its snapshot {} was broken until {}'
                  .format(builder, build_snapshot, broken_until_snapshot))
              continue
          else:
            pres.step_text = 'Unable to determine if build is broken.'

          # Refresh the criticality of the builders.
          build.critical = (
              bb_common_pb2.YES
              if builder_config.general.critical.value else bb_common_pb2.NO)
          completed_builds.append(build)

      presentation.logs['skip log'] = skip_log
      presentation.properties[
          'count_broken_before_rebuilds'] = count_broken_before_rebuilds
      return completed_builds

  def get_forced_rebuilds(
      self, gerrit_changes: List[bb_common_pb2.GerritChange]) -> Set[str]:
    """Gets a list of builders whose builds should not be reused.

    Compiles a list of all builders whose builds should not be reused as
    indicated by the Gerrit changes' commit messages. For multiple changes, the
    union of these list is returned.

    Args:
      gerrit_changes: Gerrit changes applied to this run.

    Returns:
      forced_rebuilds: A set of builder names or 'all' if no builds can be
        reused.
    """
    with self.m.step.nest('check disallow recycled builds') as pres:
      forced_rebuilds = self.m.git_footers.get_footer_values(
          gerrit_changes, self.DISALLOW_RECYCLED_BUILDS_FOOTER)

      if not forced_rebuilds:
        pres.step_text = 'no forced rebuilds'
        return forced_rebuilds

      pres.logs['found footer values'] = 'found value(s): %s' % ','.join(
          sorted(list(forced_rebuilds)))

      if 'all' in forced_rebuilds:
        pres.step_text = 'rebuild all targets'
        return {'all'}

      if 'test-failures' in forced_rebuilds:
        test_failure_builders = self.m.cros_history.get_test_failure_builders()
        forced_rebuilds.remove('test-failures')
        forced_rebuilds.update(test_failure_builders)

      pres.logs['forced rebuilds'] = sorted(list(forced_rebuilds))
      pres.step_text = 'force rebuild %s target(s)' % len(forced_rebuilds)
      return forced_rebuilds

  @staticmethod
  def get_slim_builder_name(builder_name: str) -> str:
    """Returns to the name of the slim variant of the builder.

    Args:
      builder_name: The name of the builder for which to get the slim builder
        variant name.

    Returns:
       The slim builder name.
    """
    builder_spec, env_suffix = builder_name.rsplit('-', 1)
    return builder_spec + '-slim-' + env_suffix

  def _choose_snapshots(
      self, original_internal: GitilesCommit, original_external: GitilesCommit,
      gerrit_changes: List[GerritChange], internal_manifest: ManifestProject,
      necessary_builder_names: List[str]
  ) -> Tuple[GitilesCommit, GitilesCommit]:
    """Returns chosen manifest snapshot to run CQ with.

    Args:
      original_internal: Latest internal manifest snapshot.
      original_external: Latest external manifest snapshot.
      gerrit_changes: List of changes to be tested by CQ.
      internal_manifest: Manifest project for the internal snapshot.
      necessary_builder_names: The names of the builders that will be scheduled.

    Returns:
      chosen_internal: The internal manifest snapshot that CQ will run with.
      chosen_external: The external manifest snapshot that CQ will run with.

    """
    chosen_internal = original_internal
    chosen_external = original_external
    original_internal_id = original_internal.id
    original_external_id = original_external.id if original_external else None

    with self.m.step.nest('looks for green') \
      as presentation, self.m.failures.ignore_exceptions():

      # Return early if LFG is not enabled on this run.
      if not self.m.looks_for_green.should_lfg(gerrit_changes):
        presentation.step_text = 'CQ looks not enabled. Using original snapshot'
        return chosen_internal, chosen_external

      self.m.looks_for_green.resize_lfg_lookback(gerrit_changes,
                                                 necessary_builder_names)

      requested_snapshot_builders = self.m.looks_for_green.get_requested_snapshot_builders(
          necessary_builder_names)
      suggested_internal = self.m.looks_for_green.find_green_snapshot(
          requested_snapshot_builders=requested_snapshot_builders)

      if not suggested_internal:
        presentation.step_text = 'No green snapshot found. Using latest minted snapshot.'
        return chosen_internal, chosen_external

      cq_looks_log = []
      log = (
          f'Looks for green: Replacing internal snapshot {original_internal_id} with '
          f'{suggested_internal.commit_sha}')
      cq_looks_log.append(log)
      with self.m.step.nest('set green snapshot'):
        chosen_internal.id = suggested_internal.commit_sha
        # Use external snapshot generated by same annealing run.
        suggested_external_id = self.m.cros_source.get_external_snapshot_commit(
            internal_manifest.path, chosen_internal.id)
        if chosen_external is not None:
          chosen_external.id = suggested_external_id
        else:
          chosen_external = GitilesCommit(id=suggested_external_id)
        cq_looks_log.append(
            f'Looks for green: Replacing external snapshot {original_external_id} with '
            f'{suggested_external_id}')
      with self.m.step.nest('checking mergability'):
        try:
          with self.m.context(cwd=self.m.cros_source.workspace_path):
            self.m.cros_source.sync_checkout(chosen_internal)
            # This step will throw a StepFailure if changes cannot be applied
            # to chosen snapshot.
            self.m.workspace_util.apply_changes()
            any_merge_commit = any(
                self.m.gerrit.is_merge_commit(c.change, c.host)
                for c in gerrit_changes)
            # If changes could not be cherry-picked (and they are not merge commits),
            # they will be merged instead. This is bad for LFG as only a single repo
            # will be fast-forwarded and CQ will have to rebuild all of the fast-forwarded
            # code. Instead skip LFG. b/322174445
            if (not any_merge_commit and
                self.m.cros_source.git_strategy is GitStrategy.MERGE):
              self.m.looks_for_green.stats.status = LooksForGreenStatus.STATUS_SKIPPED_FAILED_CHERRY_PICK
              self.m.looks_for_green.set_stats()
              raise recipe_api.StepFailure('CL(s) cannot be cherry-picked!')
          # Manifest-internal needs to be sync'ed separately.
          # It is used by testplannerv1. b/315475873
          with self.m.context(cwd=internal_manifest.path):
            self.m.git.checkout(chosen_internal.id, force=True)
          cq_looks_log.append(
              f'Changes are submittable with internal snapshot {suggested_internal.commit_sha}, external snapshot {suggested_external_id}'
          )
          presentation.step_text = 'Found green snapshot.'
        except recipe_api.StepFailure:
          self.m.looks_for_green.stats.status = (
              LooksForGreenStatus.STATUS_SKIPPED_FAILED_CHERRY_PICK)
          self.m.looks_for_green.set_stats()
          presentation.step_text = 'Failed to cherry-pick on green snapshot. Using original snapshot.'
          chosen_internal.id = original_internal_id
          chosen_external.id = original_external_id
          with self.m.step.nest('resetting to original snapshot'):
            cq_looks_log.append(
                'Cannot merge gerrit changes onto internal snapshot'
                f'{suggested_internal.commit_sha}, external snapshot'
                f'{suggested_external_id}. Falling back to latest '
                f'internal snapshot {original_internal_id}, external snapshot {original_external_id}'
            )
            with self.m.context(cwd=self.m.cros_source.workspace_path):
              self.m.cros_source.sync_checkout(chosen_internal)
              self.m.workspace_util.apply_changes()
            with self.m.context(cwd=internal_manifest.path):
              self.m.git.checkout(chosen_internal.id, force=True)
      presentation.logs['cq looks log'] = cq_looks_log

    # Set the orchestrator's output gitiles commit to the chosen internal
    # snapshot. This is done because users and tooling expect that the
    # orchestrator's output gitiles commit is the snapshot that is actually
    # built by child builders.
    self.m.src_state.gitiles_commit = chosen_internal

    return chosen_internal, chosen_external
