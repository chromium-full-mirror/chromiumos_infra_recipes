# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Functions for end-to-end test planning."""

import base64
import datetime
import itertools
import re
from collections import defaultdict
from typing import Iterable, List, Optional, Union
from dataclasses import dataclass

from google.protobuf import json_format
from google.protobuf import text_format
from google.protobuf import message

from PB.go.chromium.org.luci.buildbucket.proto.build import Build
from PB.chromiumos.test.api.v1 import plan as plan_pb2
from PB.chromiumos.test.plan import source_test_plan as source_test_plan_pb2
from PB.testplans.generate_test_plan import GenerateTestPlanRequest, GenerateTestPlanResponse
from recipe_engine.config_types import Path
from recipe_engine import recipe_api

from RECIPE_MODULES.recipe_engine.time.api import exponential_retry


# SourceTestPlan pointing to the legacy_default Starlark files, will be used
# when MigrationConfigs set fallback_to_default and no relevant plans are found.
LEGACY_DEFAULT_AUTOTEST_HW_PLAN = source_test_plan_pb2.SourceTestPlan.TestPlanStarlarkFile(
    host='chrome-internal.googlesource.com',
    project='chromeos/config-internal',
    path='test/plans/v2/ctpv1_compatible/legacy_default_autotest_hw.star',
)
LEGACY_DEFAULT_TAST_HW_PLAN = source_test_plan_pb2.SourceTestPlan.TestPlanStarlarkFile(
    host='chrome-internal.googlesource.com',
    project='chromeos/config-internal',
    path='test/plans/v2/ctpv1_compatible/legacy_default_tast_hw.star',
)
LEGACY_DEFAULT_VM_TEST_PLAN = source_test_plan_pb2.SourceTestPlan.TestPlanStarlarkFile(
    host='chrome-internal.googlesource.com',
    project='chromeos/config-internal',
    path='test/plans/v2/ctpv1_compatible/legacy_default_vm.star',
)

FALLBACK_DEFAULT_SOURCE_TEST_PLAN = source_test_plan_pb2.SourceTestPlan(
    test_plan_starlark_files=[
        LEGACY_DEFAULT_TAST_HW_PLAN,
        LEGACY_DEFAULT_AUTOTEST_HW_PLAN,
        LEGACY_DEFAULT_VM_TEST_PLAN,
    ])

@dataclass(frozen=True)
class StarlarkPackage:
  """Defines a Starlark file that can be executed.

  All load statements must use paths under 'root'. 'main' is the main file that
  is executed. Note that 'main' does not need to be in the top-level dir of
  root'; this allows the common case where 'root' is the root of a repo and
  'main' is a file within the repo (and all the load paths are included in the
  repo).

  This class is ordered and hashable.

  Args:
    root: Path that 'main' and all loaded files must be under. Often the root of
      a repo.
    main: Path to the Starlark file to execute.
    template_parameters: TemplateParameters to execute the Starlark file with,
      may be empty.
  """
  root: str
  main: str
  template_parameters: source_test_plan_pb2.SourceTestPlan.TestPlanStarlarkFile.TemplateParameters

  def __hash__(self) -> int:
    return hash((self.root, self.main,
                 json_format.MessageToJson(self.template_parameters)))

  def __lt__(self, other) -> bool:
    return (self.root, self.main,
            json_format.MessageToJson(
                self.template_parameters)) < (other.root, other.main,
                                              json_format.MessageToJson(
                                                  other.template_parameters))

class CrosTestPlanV2Api(recipe_api.RecipeApi):
  """A module for generating and parsing test plans for CTP v2."""

  def __init__(self, properties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._properties = properties

  @property
  def generate_ctpv1_format(self):
    return self._properties.generate_ctpv1_format

  def _get_project_migration_config(self, host, project):
    """Looks up the MigrationConfig for host and project.

    Returns None if no MigrationConfig is found.
    """
    for mc in self._properties.migration_configs:
      if mc.host == host and re.match('^{}$'.format(mc.project), project):
        return mc

    return None

  def is_bazel_builder(self, builder_name: str) -> bool:
    """Returns whether builder_name is a Bazel builder.

    Bazel builders are filtered out of testing right now, this is a simple filter
    that just works on the name. In the long-term, Bazel builders will need to
    be differentiated from Portage builders in test planning.
    """
    return '-bazel-' in builder_name

  def enabled_on_changes(self, gerrit_changes):
    """Returns true if test planning v2 is enabled on gerrit_changes.

    Config controlling what changes are enabled is in the ProjectMigrationConfig
    of this module's properties.
    """
    enabled = self._internal_enabled_on_changes(gerrit_changes)
    self.m.easy.set_properties_step(test_planning_v2_enabled=enabled)
    return enabled

  def _internal_enabled_on_changes(self, gerrit_changes):
    """Does the core computation of whether test planning v2 is enabled.

    The public enabled_on_changes method calls this method and does follow-up
    actions, such as setting output properties.
    """
    with self.m.step.nest('check test planning v2 enabled') as presentation:
      if not gerrit_changes:
        raise ValueError('gerrit_changes must be non-empty')

      for gc in gerrit_changes:
        migration_config = self._get_project_migration_config(
            gc.host, gc.project)

        # If there is no ProjectMigrationConfig for a (host, project) pair, do
        # not enable v2.
        if not migration_config:
          presentation.step_text = (
              'no migration config found for ({}, {}), not enabling test planning v2'
              .format(gc.host, gc.project))
          return False

        for regexp in migration_config.project_blocklist:
          if re.match('^{}$'.format(regexp), gc.project):
            presentation.step_text = 'project {} is blocklisted, not enabling test planning v2'.format(
                gc.project)
            return False

        if not migration_config.file_allowlist_regexps:
          raise ValueError(
              'file_allowlist_regexps must be non-empty, got config "{}"'
              .format(migration_config))

        patch_set = self.m.gerrit.fetch_patch_set_from_change(
            gc, include_files=True)

        in_branch_allowlist = False
        for regexp in migration_config.branch_allowlist_regexps:
          if re.match('^{}$'.format(regexp), patch_set.branch):
            in_branch_allowlist = True
            break

        if not in_branch_allowlist:
          presentation.step_text = (
              'branch "{}" not in allow list, not enabling test planning v2'
              .format(patch_set.branch))
          return False

        for path in patch_set.file_infos:
          in_file_allowlist = False
          for regexp in migration_config.file_allowlist_regexps:
            if re.match('^{}$'.format(regexp), path):
              in_file_allowlist = True
              break

          # All files in the change must be in the allowlist.
          if not in_file_allowlist:
            presentation.step_text = (
                'path "{}" not in allow list, not enabling test planning v2'
                .format(path))
            return False

          # All files in the change must not be in the blocklist.
          for regexp in migration_config.file_blocklist_regexps:
            if re.match('^{}$'.format(regexp), path):
              presentation.step_text = (
                  'path "{}" in block list, not enabling test planning v2'
                  .format(path))
              return False

      presentation.step_text = 'enabling test planning v2'
      return True

  def validate(self, directory: str) -> None:
    """Call test_plan validate on directory.

    Raises a StepFailure if validation fails, otherwise returns None.

    Args:
      directory: Path to a directory to validate. Note that this should be a
          directory, not a DIR_METADATA file. Any DIR_METADATA files in a
          subdirectory of directory will also be validated.
    """
    args = ['validate', '-loglevel', 'debug']
    if self._properties.validate_tag_criteria_non_empty:
      args.append('-checktagcriteria')
    args.append(directory)
    self.m.gobin.call('test_plan', args,
                      step_name='test_plan validate {}'.format(directory))

  # TODO(b/277909893): This is called at least twice in a build, determine a
  # caching strategy.
  def relevant_plans(self, gerrit_changes):
    """Call test_plan relevant-plans.

    Args:
      * gerrit_changes (list[common_pb2.GerritChange]): Changes to test, must be
          non-empty.

    Returns:
      A list of relevant SourceTestPlans
    """
    with self.m.step.nest('find relevant plans') as pres, \
       self.m.context(infra_steps=True):

      # Split up the input gerrit_changes by (host, project), and run test_plan
      # separately on them. If test_plan returns no relevant plans for a given
      # (host, project), lookup the MigrationConfig and return
      # FALLBACK_DEFAULT_SOURCE_TEST_PLAN if fallback_to_default is set.
      host_project_to_gerrit_changes = defaultdict(list)
      for gc in gerrit_changes:
        host_project_to_gerrit_changes[(gc.host, gc.project)].append(gc)

      relevant_plans = []
      for (host, project), gcs in host_project_to_gerrit_changes.items():
        with self.m.step.nest(project) as inner_pres:
          cmd = [
              'relevant-plans',
              '-loglevel',
              'debug',
          ]

          for gc in gcs:
            cmd += ['-cl', self.m.gerrit.parse_gerrit_change_url(gc)]

          output = self.m.path.mkdtemp(prefix='test_plan')

          cmd += ['-out', output]

          self.m.gobin.call('test_plan', cmd, step_name='call test_plan')

          # Output contains relevant plans in separate textproto files.
          output_files = self.m.file.listdir(
              'list output files', output,
              test_data=['relevant_plan_1.textpb', 'relevant_plan_2.textpb'])

          for f in output_files:
            output_raw = self.m.file.read_raw(
                'read output {}'.format(f),
                f,
                test_data=text_format.MessageToString(
                    self.test_api.kernel_source_test_plan()),
            )

            plan = source_test_plan_pb2.SourceTestPlan()
            text_format.Parse(output_raw, plan, allow_unknown_field=True)
            relevant_plans.append(plan)

          migration_config = self._get_project_migration_config(host, project)
          # The (host, project) should have a migration config defined if
          # relevant_plans is being called, because enabled_on_changes should be
          # called before (which returns false if any (host, project) doesn't
          # have a migration config). Check anyway, consider asserting this in
          # the future.
          if (not output_files and migration_config and
              migration_config.fallback_to_default):
            inner_pres.step_text = (
                'No relevant plans found for ({}, {}), but fallback_to_default is set on MigrationConfig'
                .format(host, project))
            if FALLBACK_DEFAULT_SOURCE_TEST_PLAN not in relevant_plans:
              relevant_plans.append(FALLBACK_DEFAULT_SOURCE_TEST_PLAN)
      pres.logs['relevant_plans'] = '\n\n,'.join(
          json_format.MessageToJson(p) for p in relevant_plans)
      # De-dupe relevant plans before writing them to a property.
      pres.properties['relevant_plans'] = list(
          set(json_format.MessageToJson(p) for p in relevant_plans))
      return relevant_plans

  def dirmd_update(self, table: str):
    """Call test_plan chromeos-dirmd-update.

    Args:
      * table: BigQuery table to upload to, in the form
        <project>.<dataset>.<table>. Required. The table will be created if it
        doesn't already exist, and the schema will be updated if it doesn't
        match the DirBQRow schema.
    """
    with self.m.step.nest('dirmd update'), self.m.context(infra_steps=True):
      self.m.gobin.call('test_plan', [
          'chromeos-dirmd-update',
          '-crossrcroot',
          self.m.src_state.workspace_path,
          '-table',
          table,
          '-loglevel',
          'debug',
      ], step_name='call test_plan')

  @exponential_retry(retries=3, delay=datetime.timedelta(minutes=1))
  def _download_config_pb(
      self,
      repository_url: str,
      file_path: str,
      output_dir: Path,
      test_output_message: message.Message,
  ) -> Path:
    """Fetch a protobuf from Gitiles and write to a local temp file.

    Args:
      * repository_url: Full URL to the repository.
      * file_path: Relative path to the file from the repository root.
      * output_dir: Path to a directory to download the file to.
      * test_output_message (google.protobuf.message.Message): A message to
        write as test data.

    Returns:
      * Path to the file where the protobuf was written.
    """
    test_output_contents = base64.b64encode(
        json_format.MessageToJson(test_output_message).encode())
    contents = self.m.gitiles.download_file(
        repository_url,
        file_path,
        step_test_data=lambda: self.m.gitiles.test_api.
        make_encoded_file_from_bytes(test_output_contents),
    )

    basename = self.m.path.basename(file_path)
    output = self.m.path.join(output_dir, basename)
    self.m.file.write_raw('write {}'.format(basename), output, contents)

    return output

  def _download_build_metadata(self, output_dir: Path) -> Path:
    return self._download_config_pb(
        'https://chrome-internal.googlesource.com/chromeos/config-internal',
        'build/generated/build_metadata.jsonproto',
        output_dir,
        test_output_message=self.test_api.build_metadata_list(),
    )

  def _download_dut_attributes(self, output_dir: Path) -> Path:
    return self._download_config_pb(
        'https://chromium.googlesource.com/chromiumos/config',
        'generated/dut_attributes.jsonproto',
        output_dir,
        test_output_message=self.test_api.dut_attribute_list(),
    )

  def _download_build_configs(self, output_dir: Path) -> Path:
    return self._download_config_pb(
        'https://chrome-internal.googlesource.com/chromeos/infra/config',
        'generated/builder_configs.binaryproto',
        output_dir,
        test_output_message=self.test_api.builder_configs(),
    )

  def _download_config_bundle_list(self, output_dir: Path) -> Path:
    return self._download_config_pb(
        'https://chrome-internal.googlesource.com/chromeos/config-internal',
        'hw_design/generated/configs.jsonproto',
        output_dir,
        test_output_message=self.test_api.config_bundle_list(),
    )

  def _download_board_priority_list(self, output_dir: Path) -> Path:
    return self._download_config_pb(
        'https://chrome-internal.googlesource.com/chromeos/config-internal',
        'board_config/generated/board_priority.cfg',
        output_dir,
        test_output_message=self.test_api.board_priority_list(),
    )

  def _get_args_for_starlark_pkgs(
      self, starlark_pkgs: List[StarlarkPackage]) -> Iterable[str]:
    """Compute the -plan and -templateparameter args for starlark_pkgs.

    There are enough relevant details in forming the -plan and
    -templateparameter args to create a separate function. For example,
    de-duping Starlark packages and filtering empty TemplateParameters.

    Args:
      starlark_pkgs: StarlarkPackages to generate arguments for.

    Returns: A list of -plan and -templateparameter args.
    """
    plan_paths = []
    template_parameters_args = []

    # Note that starlark_pkgs may contain duplicates, in this case each
    # unique package is only added to the args once.
    for package in sorted(list(set(starlark_pkgs))):
      plan_path = self.m.path.join(package.root, package.main)

      # Plan paths may be duplicated if a StarlarkPackage has different
      # TemplateParameters for the same file.
      if plan_path not in plan_paths:
        plan_paths.append(plan_path)

      # If template_parameters is non-empty form an arg
      # "<plan>:'<template parameters jsonpb>'"
      if package.template_parameters != source_test_plan_pb2.SourceTestPlan.TestPlanStarlarkFile.TemplateParameters(
      ):
        template_parameter_json = json_format.MessageToJson(
            package.template_parameters, indent=0).replace('\n', '')
        template_parameters_args.append(
            f"{plan_path}:'{template_parameter_json}'")

    return itertools.chain.from_iterable([['-plan', p] for p in plan_paths] +
                                         [['-templateparameter', a]
                                          for a in template_parameters_args])

  def generate_hw_test_plans(
      self,
      starlark_packages: List[StarlarkPackage],
      generate_test_plan_request: Optional[GenerateTestPlanRequest] = None,
  ) -> Union[List[GenerateTestPlanResponse], List[plan_pb2.HWTestPlan]]:
    """Runs the test_plan Go infra binary to get HWTestPlans.

    Args:
      * starlark_packages (list[StarlarkPackage]): Paths to Starlark files to
        evaluate to get HWTestPlans. Note that StarlarkPackages must be used
        instead of single files because the Starlark files can import each
        other. If there are duplicate StarlarkPackages (same root and main file)
        each unique package will only be added once.
      * generate_test_plan_request (GenerateTestPlanRequest): A
        GenerateTestPlanRequest for calling testplan with CTPV1 compatibility.

    Returns:
      A list of generated HWTestPlans or GenerateTestPlanResponse if
        generate_ctpv1_format is true.
    """
    with self.m.step.nest('generate hw test plans') as pres, self.m.context(
        infra_steps=True):
      if self.generate_ctpv1_format != (generate_test_plan_request is not None):
        raise ValueError(
            'generate_test_plan_request should be set iff the generate_ctpv1_format property is set'
        )

      input_path = self.m.path.mkdtemp()

      with self.m.step.nest('write input files'):
        # TODO(b/182898188): Read BuildMetadataList specific to the build when
        # available. For now, just read the global one from config-internal.
        build_metadata_list_path = self._download_build_metadata(input_path)
        config_bundle_list_path = self._download_config_bundle_list(input_path)
        dut_attribute_list_path = self._download_dut_attributes(input_path)

      out_path = (
          self.m.path.join(input_path, 'generatetestplanresp.binaryproto')
          if self.generate_ctpv1_format else self.m.path.join(
              input_path, 'hw_test_plans.jsonproto'))

      args = [
          'generate',
          '-loglevel',
          'debug',
          '-dutattributes',
          dut_attribute_list_path,
          '-buildmetadata',
          build_metadata_list_path,
          '-configbundlelist',
          config_bundle_list_path,
          '-out',
          out_path,
      ]

      if self.generate_ctpv1_format:
        board_priority_list_path = self._download_board_priority_list(
            input_path)
        args.extend(['-boardprioritylist', board_priority_list_path])

        builder_configs_path = self._download_build_configs(input_path)
        args.extend(['-builderconfigs', builder_configs_path])

        req_path = input_path.join('generatetestplanreq.binaryproto')
        self.m.file.write_raw(
            'write generatetestplanreq binaryproto', req_path,
            generate_test_plan_request.SerializeToString(deterministic=True))
        pres.logs[
            'generatetestplanreq.binaryproto'] = generate_test_plan_request.SerializeToString(
                deterministic=True)

        args.append('-ctpv1')
        args.extend(['-generatetestplanreq', req_path])

      args.extend(self._get_args_for_starlark_pkgs(starlark_packages))

      self.m.gobin.call('test_plan', args, step_name='test_plan generate')

      if self.generate_ctpv1_format:
        output = self.m.file.read_raw(
            'read output ' + out_path,
            out_path,
            test_data=self.test_api.generate_test_plan_response()
            .SerializeToString(deterministic=True),
        )
        resp = GenerateTestPlanResponse.FromString(output)
        pres.logs['v1-compatible response'] = str(resp)

        return resp

      hw_test_plans = []
      output = self.m.file.read_raw(
          'read output ' + out_path, out_path, test_data='\n'.join(
              json_format.MessageToJson(rule).replace('\n', '')
              for rule in self.test_api.hw_test_plans()))
      for line in output.splitlines():
        plan = plan_pb2.HWTestPlan()
        json_format.Parse(line, plan)
        hw_test_plans.append(plan)

      pres.logs['hw test plans'] = '\n'.join(str(p) for p in hw_test_plans)

      return hw_test_plans

  def get_testable_builders(self, starlark_packages: List[StarlarkPackage],
                            builds: List[Build]) -> List[str]:
    """Runs the test_plan Go infra binary to get a list of testable builders.

    Args:
      starlark_packages: Paths to Starlark files to evaluate to get testable
          builders. Note that StarlarkPackages must be used instead of single
          files because the Starlark files can import each other. If there are
          duplicate StarlarkPackages (same root and main file) each unique
          package will only be added once.
      builds: The list of builds considered for this CQ run.

    Returns:
      A list of the names of the testable builders.
    """
    with self.m.step.nest('get testable builders') as pres:
      input_path = self.m.path.mkdtemp()

      args = [
          'get-testable',
          '-dutattributes',
          self._download_dut_attributes(input_path),
          '-buildmetadata',
          self._download_build_metadata(input_path),
          '-configbundlelist',
          self._download_config_bundle_list(input_path),
          '-builderconfigs',
          self._download_build_configs(input_path),
      ]

      args.extend(self._get_args_for_starlark_pkgs(starlark_packages))

      builds_input_path = input_path.join('builds.jsonl')
      builds_jsonl = '\n'.join([
          json_format.MessageToJson(b, indent=0).replace('\n', '')
          for b in builds
          if 'build_target' in b.input.properties
      ])

      self.m.file.write_text('write builds.jsonl', builds_input_path,
                             builds_jsonl, include_log=True)
      args.extend(['-builds', builds_input_path])

      test_return = ' '.join([b.builder.builder for b in builds])
      test_return += '\n'
      self.m.gobin.call(
          'test_plan', args, step_name='test_plan get-testable',
          stdout=self.m.raw_io.output_text(add_output_log=True),
          step_test_data=lambda: self.m.raw_io.test_api.stream_output_text(
              test_return))

      testable_builders = sorted(self.m.step.active_result.stdout.split())

      # Bazel builders should not be considered testable right now.
      # TODO(b/330338112): Add test planning support for Bazel builders.
      testable_builders = [
          b for b in testable_builders if not self.is_bazel_builder(b)
      ]

      pres.logs['testable_builders'] = testable_builders

      return testable_builders
