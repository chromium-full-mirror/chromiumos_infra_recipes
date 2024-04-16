# -*- coding: utf-8 -*-

# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module for determining if a build is unnecessary."""

from collections import namedtuple
from typing import List, Optional

from google.protobuf import json_format

from RECIPE_MODULES.chromeos.gerrit.api import PatchSet

from PB.chromite.api.depgraph import DepGraph
from PB.chromite.api.depgraph import GetBuildDependencyGraphRequest
from PB.chromite.api.depgraph import ListRequest
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import ProtoBytes as common_proto_bytes
from PB.chromiumos.generate_build_plan import GenerateBuildPlanRequest
from PB.chromiumos.generate_build_plan import GenerateBuildPlanResponse
from PB.go.chromium.org.luci.buildbucket.proto import common as bbcommon_pb2
from PB.testplans.common import ProtoBytes as testplans_proto_bytes
from PB.testplans.pointless_build import PointlessBuildCheckRequest
from PB.testplans.pointless_build import PointlessBuildCheckResponse
from recipe_engine import recipe_api

PlannedBuilders = namedtuple(
    'PlannedBuilders',
    ['necessary', 'global_irrelevance_skipped', 'run_when_rules_skipped'])


class CrosRelevanceApi(recipe_api.RecipeApi):
  """A module for determining if a build is unnecessary."""

  # A git footer that can be included in commit messages to tell the cq run to
  # disallow using slim builds for the given builders or all.
  DISALLOW_SLIM_BUILDS_FOOTER = 'Disallow-Slim-Builds'

  # A git footer that can be included in commit messages to tell the cq run to
  # force the builds to be relevant. Does not prevent them being recycled.
  FORCE_RELEVANT_BUILDS_FOOTER = 'Force-Relevant-Builds'

  def __init__(self, properties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._properties = properties
    # Toolchain changes have been detected, None if not checked.
    self._toolchain_cls_applied = None

  @property
  def toolchain_cls_applied(self) -> Optional[bool]:
    """Whether there are toolchain CLs applied to the source tree."""
    if (self._test_data.enabled and
        self._test_data.get('toolchain_cls_applied', None) is not None):
      return self._test_data.get('toolchain_cls_applied')
    return self._toolchain_cls_applied

  @toolchain_cls_applied.setter
  def toolchain_cls_applied(self, value: Optional[bool]):
    self._toolchain_cls_applied = value

  def run_build_planner(self, builder_configs, gerrit_changes, gitiles_commit,
                        name=None):
    """Determines which builders must be run (and which can be skipped).

    This filters on preconfigured RunWhen rules, as well as on rules allowing
    skipping of image builders. Image builders are those that run the
    build_target recipe, producing an IMAGE_ZIP CrOS artifact.

    Args:
      builder_configs (list[chromiumos.BuilderConfig]): builder configs to
          consider for skipping.
      gerrit_changes (bbcommon_pb2.GerritChange): The Gerrit Changes to be
          applied for the build, if any.
      gitiles_commit (bbcommon_pb2.GitilesCommit): The manifest-internal
          snapshot Gitiles commit.
      name (str): The step name.

    Returns:
      PlannedBuilders: Necessary and skipped builders as a tuple.
    """
    with self.m.step.nest(name or 'plan builds') as presentation:
      request = GenerateBuildPlanRequest(
          gitiles_commit=common_proto_bytes(
              serialized_proto=bbcommon_pb2.GitilesCommit.SerializeToString(
                  gitiles_commit)))
      request.builder_configs.extend(builder_configs)
      for gc in gerrit_changes:
        new_gc = request.gerrit_changes.add()
        new_gc.serialized_proto = (
            bbcommon_pb2.GerritChange.SerializeToString(gc))

      messages_path = self.m.path.mkdtemp(prefix='build-plan-')
      input_bin_file = messages_path.join('input.binaryproto')
      output_bin_file = messages_path.join('output.binaryproto')
      presentation.logs['planner_input'] = json_format.MessageToJson(request)
      self.m.file.write_raw('write input binaryproto', input_bin_file,
                            request.SerializeToString())

      cmd = [
          'generate-plan',
          '--input_binary_pb',
          input_bin_file,
          '--output_binary_pb',
          output_bin_file,
      ]
      # We don't have the entire source tree checked out, so we cannot create a
      # pinned manifest at this point.  Use default.xml, which is either a link
      # to snapshot.xml, or to the full (unpinned) manifest.
      if self.m.cros_source.manifest_branch:
        presentation.step_text = 'running on manifest branch'
        cmd.extend([
            '--manifest_file',
            self.m.src_state.build_manifest.path.join('default.xml')
        ])

      self.m.gobin.call('build_plan_generator', cmd, step_name='run planner',
                        infra_step=True)

      test_resp = GenerateBuildPlanResponse(
          builds_to_run=[b.id for b in builder_configs])
      response_bin = self.m.file.read_raw(
          'read output file', output_bin_file,
          test_data=test_resp.SerializeToString())
      result = GenerateBuildPlanResponse.FromString(response_bin)

      presentation.logs['planner_output'] = str(result)
      presentation.step_text = (
          '{} relevant, {} irrelevant builder configs'.format(
              len(result.builds_to_run),
              len(result.skip_for_global_build_irrelevance) +
              len(result.skip_for_run_when_rules)))
      necessary = [b.name for b in result.builds_to_run]
      global_irrelevance_skipped = [
          b.name for b in result.skip_for_global_build_irrelevance
      ]
      run_when_rules_skipped = [b.name for b in result.skip_for_run_when_rules]
      if not self.m.cv.active:
        return PlannedBuilders(
            necessary=necessary,
            global_irrelevance_skipped=global_irrelevance_skipped,
            run_when_rules_skipped=run_when_rules_skipped)
      return PlannedBuilders(
          necessary=self._filter_slim_builders(necessary, gerrit_changes),
          global_irrelevance_skipped=self._filter_slim_builders(
              global_irrelevance_skipped, gerrit_changes),
          run_when_rules_skipped=self._filter_slim_builders(
              run_when_rules_skipped, gerrit_changes))

  def _filter_slim_builders(self, builders, gerrit_changes):
    """Filter out slim builders and replace with standard builders as necessary.

    Replace slim CQ builders with standard CQ builders if specified in the
    commit message footer.

    Args:
      builders (string): The names of the builders to run as determined by the
        build planner.
      gerrit_changes (bbcommon_pb2.GerritChange): The Gerrit changes to be
        applied to the build.

    Returns:
      List of builders to be run.
    """
    forced_standard_builders = self._check_disallow_slim_footer(gerrit_changes)
    if 'all' in forced_standard_builders:
      return [b.replace('-slim-cq', '-cq') for b in builders]
    # Replace any slim CQ builders with the standard CQ builder if present.
    # Input builder list is returned if no builders are specified in the footer.
    return [
        b.replace('-slim-cq', '-cq')
        if b.replace('-slim-cq', '-cq') in forced_standard_builders else b
        for b in builders
    ]

  def is_cq_build_relevant(self, patch_sets: List[PatchSet],
                           dep_graph: DepGraph, force_relevant: bool = False,
                           is_pointless_test_value: bool = False) -> bool:
    """Determines if changes are relevant to the CQ run.

    If build_target is set, then the chromiumos workspace must have been
    checked out prior to calling this method. This is a requirement for
    BuildDependencyGraph checks.

    Args:
      patch_sets: The PatchSets applied to the build.
      dep_graph: The dependency graph to compare the changes against to test
          for build relevancy.
      force_relevant: Whether to always declare the build relevant.
      is_pointless_test_value: The test return value of the pointless build
          checker. Default is False, meaning the build is not pointless.

    Returns:
      bool: Whether the changes are relevant to the CQ run.
    """
    if force_relevant or self.toolchain_cls_applied:
      return True

    with self.m.step.nest('cq relevance check') as presentation:

      if not patch_sets:
        presentation.step_text = 'no changes to check for relevancy'
        return False

      check_request = PointlessBuildCheckRequest(
          ignore_known_non_portage_directories=False,
      )
      affected_paths = self.get_affected_paths(patch_sets)
      for source_path in affected_paths:
        affected_path = check_request.affected_paths.add()
        affected_path.path = source_path
      relevant_paths = _flatten_depgraph_paths(dep_graph)
      for source_path in relevant_paths:
        relevant_path = check_request.relevant_paths.add()
        relevant_path.path = source_path
      check_request.builder_name = self.m.buildbucket.build.builder.builder

      response = self.call_pointless_build_checker(check_request, presentation,
                                                   is_pointless_test_value)
      relevant = not bool(response.build_is_pointless.value)

      # Do this in a step instead of a presentation to avoid multiple lines in
      # the output properties (in led jobs).
      # TODO(seanabraham): stop writing 'pointless_build' property once Plx
      # scripts have switched over to 'relevant_build'.
      step = self.m.easy.set_properties_step(pointless_build=not relevant,
                                             relevant_build=relevant)
      step.presentation.step_text = ('build is relevant'
                                     if relevant else 'build is irrelevant')
      return relevant

  def _format_pkgs(self, pkg_list):
    print_lines = []
    for pkg in pkg_list:
      print_lines.append('({}, {}, {})'.format(pkg.category, pkg.package_name,
                                               pkg.version))
    return print_lines

  def postsubmit_relevance_check(self, gitiles_commit, dep_graph):
    """Determines if postsubmit builder is relevant for given snapshot.

    Args:
      gitiles_commit (bbcommon_pb2.GitilesCommit): The manifest-internal
          snapshot Gitiles commit.
      dep_graph (chromite.api.DepGraph): The dependency graph to compare the
          Gerrit changes against to test for build relevancy.

    Returns:
      bool: Whether any packages that target depends on have been upreved
      in the latest snapshot or the build was forced relevant.
    """
    if self._properties.force_postsubmit_relevance:
      return True

    relevance_log = []
    with self.m.step.nest('postsubmit relevance check') as pres:
      annealing_build = self.m.cros_history.get_annealing_from_snapshot(
          gitiles_commit.id)
      if not annealing_build:
        pres.step_text = 'relevant because annealing build was not found'
        return True

      upreved_pkgs = self.m.cros_history.get_upreved_pkgs(annealing_build)
      relevance_log.append('Packages upreved by Annealing:')
      relevance_log += self._format_pkgs(upreved_pkgs)
      dependent_pkgs = _flatten_depgraph_pkgs(dep_graph)
      relevance_log.append('Packages target depends on:')
      relevance_log += self._format_pkgs(dependent_pkgs)

      relevant_pkgs = []
      for pkg in upreved_pkgs:
        if pkg in dependent_pkgs:
          relevant_pkgs.append(pkg)

      relevance_log.append('Packages that are relevant:')
      relevance_log += self._format_pkgs(relevant_pkgs)
      pres.logs['relevance log'] = relevance_log
      relevant = len(relevant_pkgs) != 0
      if relevant:
        pres.step_text = 'build is relevant'
      else:
        pres.step_text = 'build is not relevant'
      return relevant

  def _are_paths_affected(self, gerrit_changes, gitiles_commit, relevant_paths,
                          test_value=None, name=None,
                          ignore_known_non_portage=False):
    """Determines if a Gerrit Change affects any files in relevant paths.

    Args:
      gerrit_changes (bbcommon_pb2.GerritChange): The Gerrit Changes to be
          applied for the build, if any.
      gitiles_commit (bbcommon_pb2.GitilesCommit): The manifest-internal
          snapshot Gitiles commit.
      relevant_paths (Iterable[str]): A collection of paths to be considered
        relevant.
      test_value (bool): The answer to use for testing, or None.
      name (str): The step name to display, defaults to 'path relevance
          check'.
      ignore_known_non_portage (bool): If we should ignore the known non
          portage paths when determining relevancy.
    Returns:
      bool: Whether the given Gerrit Change affects any of the relevant paths.
    """
    with self.m.step.nest(name or 'path relevancy check') as presentation:
      if not gerrit_changes:
        presentation.step_text = 'no changes to check for relevancy'
        return False

      gitiles_commit = gitiles_commit or bbcommon_pb2.GitilesCommit()
      check_request = PointlessBuildCheckRequest(
          gitiles_commit=testplans_proto_bytes(
              serialized_proto=bbcommon_pb2.GitilesCommit.SerializeToString(
                  gitiles_commit)),
          ignore_known_non_portage_directories=ignore_known_non_portage,
      )

      for source_path in relevant_paths:
        relevant_path = check_request.relevant_paths.add()
        relevant_path.path = source_path

      for gc in gerrit_changes:
        new_gc = check_request.gerrit_changes.add()
        new_gc.serialized_proto = (
            bbcommon_pb2.GerritChange.SerializeToString(gc))

      result = self.call_pointless_build_checker(
          check_request, presentation, is_pointless_test_value=not test_value)

      return not bool(result.build_is_pointless.value)

  def call_pointless_build_checker(self, check_request, step_presentation,
                                   is_pointless_test_value=False):
    """Returns the result of calling the Pointless Build Checker.

    Args:
      check_request (PointlessBuildCheckRequest): The request to pass into the
          pointless build checker.
      step_presentation (StepPresentation): The parent step presentation. This
          is used for adding logs to the UI.
      is_pointless_test_value (bool): The return value when testing. The default
          is False.

    Returns:
      check_result (PointlessBuildCheckResponse): The response from calling the
          Pointless Build Checker
    """
    messages_path = self.m.path.mkdtemp(prefix='pointless-build-')
    input_bin_file = messages_path.join('input.binaryproto')
    output_bin_file = messages_path.join('output.binaryproto')
    step_presentation.logs['relevance_input'] = str(check_request)
    self.m.file.write_raw('write input binaryproto', input_bin_file,
                          check_request.SerializeToString())

    cmd = [
        'check-build',
        '--input_binary_pb',
        input_bin_file,
        '--output_binary_pb',
        output_bin_file,
    ]
    if self.m.cros_source.manifest_branch:
      step_presentation.step_text = 'running on manifest branch'
      pinned_manifest = self.m.path.mkstemp(prefix='pinned-manifest')
      self.m.file.write_raw('write pinned manifest', pinned_manifest,
                            self.m.cros_source.pinned_manifest)
      cmd.extend(['--manifest_file', pinned_manifest])

    self.m.gobin.call('pointless_build_checker', cmd, step_name='run check',
                      infra_step=True)

    test_resp = PointlessBuildCheckResponse()
    test_resp.build_is_pointless.value = is_pointless_test_value
    test_data = test_resp.SerializeToString()
    response_bin = self.m.file.read_raw('read output file', output_bin_file,
                                        test_data=test_data)
    check_result = PointlessBuildCheckResponse.FromString(response_bin)
    step_presentation.logs['relevance_output'] = str(check_result)

    return check_result

  def is_depgraph_affected(self, gerrit_changes, gitiles_commit, dep_graph,
                           test_value=None, name=None):
    """Determines if a Gerrit Change affects a given dependency graph.

    Args:
      gerrit_changes (bbcommon_pb2.GerritChange): The Gerrit Changes to be
          applied for the build, if any.
      gitiles_commit (bbcommon_pb2.GitilesCommit): The manifest-internal
          snapshot Gitiles commit.
      dep_graph (chromite.api.DepGraph): The dependency graph to compare the
          Gerrit changes against to test for build relevancy.
      test_value (bool): The answer to use for testing, or None.
      name (str): The step name to display, or None for default.

    Returns:
      bool: Whether the given Gerrit Change affects the given dependency graph.
    """
    # Take the union of the relevant paths for the entire dependency graph
    # and pass it as a flat list of paths.
    relevant_paths = _flatten_depgraph_paths(dep_graph)

    return self._are_paths_affected(gerrit_changes, gitiles_commit,
                                    relevant_paths, test_value=test_value,
                                    name=(name or 'depgraph relevance check'))

  def get_dependency_graph(self, sysroot, chroot, packages=None):
    """Calculates the dependency graph for the build target & SDK

    Args:
      sysroot (Sysroot): The Sysroot being used.
      chroot (chromiumos.Chroot): The chroot it is being run in.
      packages (list[chromiumos.PackageInfo]): The packages for which to
          generate the dependency graph.

    Returns:
      (chromite.api.DepGraph, chromite.api.DepGraph): A tuple of opaque
          dependency graph objects, with the first element being the dependency
          graph for the target and the second element the graph for the
          SDK/chroot.
    """
    _dep_graph = namedtuple('_dep_graph', ['target', 'sdk'])
    with self.m.step.nest('dependency graph calculation'):
      resp = self.m.cros_build_api.DependencyService.GetBuildDependencyGraph(
          GetBuildDependencyGraphRequest(sysroot=sysroot, chroot=chroot,
                                         packages=packages))
      return _dep_graph(target=resp.dep_graph, sdk=resp.sdk_dep_graph)

  def check_force_relevance_footer(self, gerrit_changes, configs):
    """Check the incoming gerrit changes to determine if we force relevance.

    Args:
      gerrit_changes (list[GerritChange]): The gerrit changes.
      configs (list[BuilderConfig]: The Builder Configs for the build.

    Returns:
      A list of target names, derived from `configs`, to be forced relevant.
    """
    with self.m.step.nest('check force relevance') as pres:
      force_relevant_values = self.m.git_footers.get_footer_values(
          gerrit_changes, self.FORCE_RELEVANT_BUILDS_FOOTER,
          step_test_data=self.m.git_footers.test_api.step_test_data_factory(''))
      pres.logs['found footer builders'] = 'found build(s): %s' % ','.join(
          sorted(force_relevant_values))

      # Handle forcing relevance via footer value.
      force_relevant_builders = set(
          t for t in force_relevant_values if t != 'all')
      force_relevant_all = 'all' in force_relevant_values

      # Output which builders were specifically forced relevant.
      # This output property is read by the CQ auto retrier.
      if force_relevant_builders:
        pres.properties['found_force_relevant_targets'] = sorted(
            force_relevant_builders)

      f_rel = set(
          cfg.id.name
          for cfg in configs
          if cfg.id.name in force_relevant_builders or force_relevant_all)

      # If any builders which were specified to be forced relevant were not
      # already added to f_rel, then those builders are not a part of the
      # orchestrator's child specs.
      remaining_builders = force_relevant_builders - f_rel

      # Add any non-default CQ builders added via the `Force-Relevant-Builds`
      # footer if it corresponds to a valid builder CQ builder.
      if remaining_builders:
        builder_config_dict = self.m.cros_infra_config.safe_get_builder_configs(
            list(remaining_builders))
        for b, config in builder_config_dict.items():
          if config.id.type == BuilderConfig.Id.Type.CQ:
            f_rel.add(b)

      # Log a message if any builders still remain.
      remaining_builders = force_relevant_builders - f_rel
      if remaining_builders:
        pres.logs['invalid builders'] = sorted(remaining_builders)

      f_rel = sorted(f_rel)
      pres.step_text = 'force relevant %s target(s)' % len(f_rel)
      if f_rel:
        pres.logs['forced targets'] = '\n'.join(f_rel)
      return f_rel

  def _check_disallow_slim_footer(self, gerrit_changes):
    """Check the incoming gerrit changes for disallow slim builds footer.

    Args:
      gerrit_changes (list[GerritChange]): The gerrit changes.

    Returns:
      builders (set(str)): A set of builder names or 'all' if no slim builds
        should be run.
    """
    with self.m.step.nest('check disallow slim builds'):
      builders = self.m.git_footers.get_footer_values(
          gerrit_changes, self.DISALLOW_SLIM_BUILDS_FOOTER)
      return {'all'} if 'all' in builders else builders

  def get_affected_paths(self, patch_sets):
    """Returns the union of all paths in the list of patchsets.

    Args:
      patch_sets (List[PatchSet]): List of Gerrit Patchsets to be applied
        to the build, if any.

    Returns:
      List[str]: The union of all paths in the patchsets.
    """
    with self.m.step.nest('get affected paths'):
      affected_paths = []
      for patch_set in patch_sets:
        src_paths = self.m.cros_source.find_project_paths(
            patch_set.project, patch_set.branch)
        for src_path in src_paths:
          for path in patch_set.file_infos.keys():
            affected_path = '%s/%s' % (src_path, path)
            affected_paths.append(affected_path)
      return affected_paths

  def get_package_dependencies(self, sysroot, chroot, patch_sets=None,
                               packages=None, include_rev_deps=False):
    """Calculates the dependencies for the build target.

    Args:
      sysroot (Sysroot): The Sysroot being used.
      chroot (chromiumos.Chroot): The chroot it is being run in.
      patch_sets (List[PatchSet]): The changes applied to the build.
        Used to determine the affected paths. If empty / None returns package
        dependencies for all paths.
      packages (list[chromiumos.PackageInfo]): The list of packages for which to
        get dependencies. If none are specified the standard list of packages is
        used.

    Returns:
      (List[str]): A list of package dependencies for the build target.
    """
    with self.m.step.nest('get package dependencies'):
      req = ListRequest(sysroot=sysroot, chroot=chroot, packages=packages,
                        include_rev_deps=include_rev_deps)
      affected_paths = self.get_affected_paths(patch_sets)
      for path in affected_paths:
        src_path = req.src_paths.add()
        src_path.path = path
      resp = self.m.cros_build_api.DependencyService.List(req)
      return resp.package_deps


def _flatten_depgraph_paths(depgraph):
  """Returns the union of relevant paths of all packages in the depgraph.

  Args:
    depgraph (chromite.api.DepGraph)

  Returns:
    Set[str]: The union of the 'dependency_source_paths' fields for all
      packages in the depgraph.
  """
  paths = set()
  for package in depgraph.package_deps:
    for source_path in package.dependency_source_paths:
      paths.add(source_path.path)
  return paths


def _flatten_depgraph_pkgs(depgraph):
  """Returns the union of relevant packages in the depgraph.

  Args:
    depgraph (chromite.api.DepGraph)

  Returns:
    Set[PackageInfo]: The union of the 'dependency_packages' fields for all
      packages in the depgraph.
  """
  packages = []
  for package in depgraph.package_deps:
    for pkg_info in package.dependency_packages:
      packages.append(pkg_info)
  return packages
