# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import base64
import re
from collections import namedtuple, defaultdict

import six
from google.protobuf import json_format
from google.protobuf import text_format

from PB.chromiumos.test.api.v1 import plan as plan_pb2
from PB.chromiumos.test.plan import source_test_plan as source_test_plan_pb2
from PB.testplans.generate_test_plan import GenerateTestPlanResponse
from recipe_engine import recipe_api

PYTHON_VERSION_COMPATIBILITY = 'PY3'

# SourceTestPlan pointing to the legacy_default Starlark files, will be used
# when MigrationConfigs set fallback_to_default and no relevant plans are found.
FALLBACK_DEFAULT_SOURCE_TEST_PLAN = source_test_plan_pb2.SourceTestPlan(
    test_plan_starlark_files=[
        source_test_plan_pb2.SourceTestPlan.TestPlanStarlarkFile(
            host='chrome-internal.googlesource.com',
            project='chromeos/config-internal',
            path='test/plans/v2/ctpv1_compatible/legacy_default_tast_hw.star',
        ),
        source_test_plan_pb2.SourceTestPlan.TestPlanStarlarkFile(
            host='chrome-internal.googlesource.com',
            project='chromeos/config-internal',
            path='test/plans/v2/ctpv1_compatible/legacy_default_autotest_hw.star',
        ),
        source_test_plan_pb2.SourceTestPlan.TestPlanStarlarkFile(
            host='chrome-internal.googlesource.com',
            project='chromeos/config-internal',
            path='test/plans/v2/ctpv1_compatible/legacy_default_vm.star',
        )
    ])


class CrosTestPlanV2Api(recipe_api.RecipeApi):
  """A module for generating and parsing test plans for CTP v2."""

  def __init__(self, properties, *args, **kwargs):
    super(CrosTestPlanV2Api, self).__init__(*args, **kwargs)
    self._properties = properties

  def initialize(self):
    self._cipd_package = (
        self._properties.test_plan_cipd_package.encode('utf-8') or
        "chromiumos/infra/test_plan/${platform}")

    default_ref = "staging" if self.m.cros_infra_config.is_staging else "prod"
    self._cipd_ref = (
        self._properties.test_plan_cipd_ref.encode('utf-8') or default_ref)

    docker_image_name = (
        self._properties.platform_test_plan_docker_image.encode('utf-8') or
        "testplan")
    docker_tag = (
        self._properties.platform_test_plan_docker_tag.encode('utf-8') or
        default_ref)
    self._docker_image = "{}:{}".format(docker_image_name, docker_tag)
    self._migration_configs = self._properties.migration_configs
    self._test_plan_path = None

  @property
  def generate_ctpv1_format(self):
    return self._properties.generate_ctpv1_format

  def _get_project_migration_config(self, host, project):
    """Looks up the MigrationConfig for host and project.

    Returns None if no MigrationConfig is found.
    """
    for mc in self._migration_configs:
      if mc.host == host and re.match('^{}$'.format(mc.project), project):
        return mc

    return None

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
    self._ensure_test_plan()
    self.m.step('test_plan validate {}'.format(directory),
                [self._test_plan_path, 'validate', directory])

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
      self._ensure_test_plan()

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
              self._test_plan_path,
              'relevant-plans',
              '-loglevel',
              'debug',
          ]

          for gc in gcs:
            cmd += ['-cl', self.m.gerrit.parse_gerrit_change_url(gc)]

          output = self.m.path.mkdtemp(prefix='test_plan')

          cmd += ['-out', output]

          self.m.step('call test_plan', cmd)

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
          text_format.MessageToString(p) for p in relevant_plans)
      return relevant_plans

  def _ensure_test_plan(self):
    """Ensure the test_plan cli is installed.

    Source code for test_plan is under
    https://source.corp.google.com/chromium_infra/go/src/infra/cros/cmd/test_plan/.
    """
    if self._test_plan_path:
      return

    with self.m.step.nest('ensure test_plan'):
      with self.m.context(infra_steps=True):
        cipd_dir = self.m.path['start_dir'].join('cipd')

        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package(self._cipd_package, self._cipd_ref)
        self.m.cipd.ensure(cipd_dir, pkgs)

        self._test_plan_path = cipd_dir.join('test_plan')

  def _download_config_pb(self, host, project, path, output_dir,
                          test_output_message):
    """Fetch a protobuf from Gitiles and write to a local temp file.

    Args:
      * host (str): Gerrit host, e.g. chrome-internal.googlesource.com.
      * project (str): Gerrit project, e.g. chromiumos/chromite.
      * path (str): Path to the file within config-internal.
      * output_dir (str): Path to a directory to download the file to.
      * test_output_message (google.protobuf.Message): A message to write as
        test data.

    Returns:
      * Path to the file where the protobuf was written.
    """
    test_output_contents = base64.b64encode(
        six.ensure_binary(json_format.MessageToJson(test_output_message)))
    contents = self.m.gitiles.get_file(host, project, path, public=False,
                                       test_output_data=test_output_contents)

    basename = self.m.path.basename(path)
    output = self.m.path.join(output_dir, basename)
    self.m.file.write_raw('write {}'.format(basename), output, contents)

    return output

  def _ensure_docker_image(self):
    """Logs in and pulls the testplan docker image."""
    with self.m.step.nest('ensure docker image') as presentation:
      self.m.docker.ensure_installed()

      version = self.m.docker.get_version()
      if version:
        presentation.logs['docker version'] = version

      self.m.docker.login(server='us-docker.pkg.dev',
                          project='cros-registry/test-services')
      self.m.docker.pull(self._docker_image)

  # Defines a collection of Starlark files under the same root. All load
  # statements must use paths relative to 'root', and 'main' is the main file
  # that is executed. Note that 'main' does not need to be in the top-level dir
  # of 'root'; this allows the common case where 'root' is the root of a repo
  # and 'main' is a file within the repo (and all the load paths are included
  # in the repo).
  StarlarkPackage = namedtuple('StarlarkPackage', ['root', 'main'])

  def generate_hw_test_plans(
      self,
      starlark_packages,
      generate_test_plan_request=None,
  ):
    """Runs the testplan Docker image to get HWTestPlans.

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
    with self.m.step.nest('generate hw test plans') as pres:
      if self.generate_ctpv1_format != (generate_test_plan_request is not None):
        raise ValueError(
            'generate_test_plan_request should be set iff the generate_ctpv1_format property is set'
        )

      self._ensure_docker_image()

      # The testplan executable requires files for some input args. Write the
      # files under a tempdir on the host, and then mount this dir to the
      # container so testplan can read them.
      host_input_path = self.m.path.mkdtemp()
      container_input_path = '/input'

      with self.m.step.nest('write input files'):
        # TODO(b/182898188): Read BuildMetadataList specific to the build when
        # available. For now, just read the global one from config-internal.
        build_metadata_list_path = self._download_config_pb(
            'chrome-internal.googlesource.com',
            'chromeos/config-internal',
            'build/generated/build_metadata.jsonproto',
            host_input_path,
            test_output_message=self.test_api.build_metadata_list(),
        )

        config_bundle_list_path = self._download_config_pb(
            'chrome-internal.googlesource.com',
            'chromeos/config-internal',
            'hw_design/generated/configs.jsonproto',
            host_input_path,
            test_output_message=self.test_api.config_bundle_list(),
        )

        dut_attribute_list_path = self._download_config_pb(
            'chromium.googlesource.com',
            'chromiumos/config',
            'generated/dut_attributes.jsonproto',
            host_input_path,
            test_output_message=self.test_api.dut_attribute_list(),
        )

        board_priority_list_path = self._download_config_pb(
            'chrome-internal.googlesource.com',
            'chromeos/config-internal',
            'board_config/generated/board_priority.cfg',
            host_input_path,
            test_output_message=self.test_api.board_priority_list(),
        )

      out_path = (
          self.m.path.join(host_input_path, "generatetestplanresp.binaryproto")
          if self.generate_ctpv1_format else self.m.path.join(
              host_input_path, 'hw_test_plans.jsonproto'))

      # A map from input flag for testplan to the path to the input file on the
      # host.
      #
      # Note that the same mechanism is used for the output of testplan.
      arg_to_host_path = {
          '-dutattributes': dut_attribute_list_path,
          '-buildmetadata': build_metadata_list_path,
          '-configbundlelist': config_bundle_list_path,
          '-boardprioritylist': board_priority_list_path,
          '-out': out_path,
      }

      # Build a list of args to pass to docker run. For each (flag, host path)
      # tuple in arg_to_host_path, add args [<flag>, <container path>]
      args = ['generate', '-alsologtostderr', '-v', '2']

      if self.generate_ctpv1_format:
        req_path = host_input_path.join('generatetestplanreq.binaryproto')
        self.m.file.write_raw(
            'write generatetestplanreq binaryproto', req_path,
            generate_test_plan_request.SerializeToString(deterministic=True))
        args.append('-ctpv1')
        arg_to_host_path['-generatetestplanreq'] = req_path

      for arg, host_path in sorted(arg_to_host_path.items()):
        args.extend([
            arg, '{}/{}'.format(container_input_path,
                                self.m.path.basename(host_path))
        ])

      # Copy each Starlark package to the host input dir, and a '-plan' flag
      # pointing to the main file.
      #
      # Note that starlark_packages may contain duplicates, in this case each
      # unique package is only added to the args once.
      #
      # Starlark packages may share the same root, because they are in the same
      # repo. Keep track of which roots have been visited, and don't copy them
      # twice.
      visited_roots = set()
      for package in sorted(list(set(starlark_packages))):
        basename = self.m.path.basename(package.root)

        if package.root not in visited_roots:
          dest = self.m.path.join(host_input_path, basename)
          # Some repos contain symlinks to parent directories, leave symlinks as
          # symlinks instead of following them, to avoid infinite recursion.
          self.m.file.copytree('copy ' + basename, package.root, dest,
                               symlinks=True)
          visited_roots.add(package.root)

        args.extend([
            '-plan', '{}/{}/{}'.format(container_input_path, basename,
                                       package.main)
        ])

      # Run the docker image. The directory with the input files is mounted to
      # the container.
      self.m.docker.run(
          self._docker_image,
          cmd_args=args,
          dir_mapping=[(host_input_path, container_input_path)],
      )

      if self.generate_ctpv1_format:
        output = self.m.file.read_raw(
            'read output ' + out_path,
            out_path,
            test_data=self.test_api.generate_test_plan_response()
            .SerializeToString(deterministic=True),
        )
        resp = GenerateTestPlanResponse.FromString(output)
        pres.logs['v1-compatible response'] = [str(resp)]
        return resp

      # Read the output HWTestPlans, which are readable on the host because
      # of the mounted directory.
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
