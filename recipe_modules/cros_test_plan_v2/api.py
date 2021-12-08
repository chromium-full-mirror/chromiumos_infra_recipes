# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import base64
import re

from recipe_engine import recipe_api

from google.protobuf import json_format
from google.protobuf import text_format

from PB.chromiumos.test.api.v1 import plan as plan_pb2
from PB.chromiumos.test.plan import source_test_plan as source_test_plan_pb2


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

    # Map from (host, project) -> ProjectMigrationConfig, for lookup when
    # enabled_on_changes is called.
    self._host_project_to_migration_config = {
        (mc.host, mc.project): mc for mc in self._properties.migration_configs
    }

  def enabled_on_changes(self, gerrit_changes):
    """Returns true if test planning v2 is enabled on gerrit_changes.

    Config controlling what changes are enabled is in the ProjectMigrationConfig
    of this module's properties.
    """
    with self.m.step.nest('check test planning v2 enabled') as presentation:
      if not gerrit_changes:
        raise ValueError('gerrit_changes must be non-empty')

      for gc in gerrit_changes:
        migration_config = self._host_project_to_migration_config.get(
            (gc.host, gc.project))

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

        for path in patch_set.file_infos:
          in_allowlist = False
          for regexp in migration_config.file_allowlist_regexps:
            if re.match('^{}$'.format(regexp), path):
              in_allowlist = True
              break

          # All files in the change must be in the allowlist.
          if not in_allowlist:
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

  def relevant_plans(self, gerrit_changes):
    """Call test_plan relevant-plans.

    Args:
      * gerrit_changes (list[common_pb2.GerritChange]): Changes to test, must be
          non-empty.

    Returns:
      A list of relevant SourceTestPlans
    """
    with self.m.step.nest('find relevant plans'), \
       self.m.context(infra_steps=True):
      self._ensure_test_plan()

      cmd = [
          self._test_plan_path,
          'relevant-plans',
          '-loglevel',
          'debug',
      ]

      for gc in gerrit_changes:
        cmd += ['-cl', self.m.gerrit.parse_gerrit_change_url(gc)]

      output = self.m.path.mkdtemp(prefix='test_plan')

      cmd += ['-out', output]

      self.m.step('call test_plan', cmd)

      # Output contains relevant plans in separate textproto files.
      output_files = self.m.file.listdir(
          'list output files',
          output,
      )
      relevant_plans = []

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

      return relevant_plans

  def _ensure_test_plan(self):
    """Ensure the test_plan cli is installed.

    Source code for test_plan is under
    https://source.corp.google.com/chromium_infra/go/src/infra/cros/cmd/test_plan/.
    """
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
        json_format.MessageToJson(test_output_message))
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

  def generate_hw_test_plans(self, starlark_files):
    """Runs the testplan Docker image to get HWTestPlans.

    Args:
      * starlark_files (list[Path]): Paths to Starlark files to evaluate to get
        HWTestPlans.


    Returns:
      A list of generated HWTestPlans.
    """
    with self.m.step.nest('generate hw test plans'):
      self._ensure_docker_image()

      # The testplan executable requires files for some input args. Write the
      # files under a tempdir on the host, and then mount this dir to the
      # container so testplan can read them.
      host_input_path = self.m.path.mkdtemp()
      container_input_path = '/input'

      with self.m.step.nest('write input files'):
        # TODO(b/182898188): Read BuildMetadataList and FlatConfigList specific to
        # the build when available. For now, just read the global one from
        # config-internal.
        build_metadata_list_path = self._download_config_pb(
            'chrome-internal.googlesource.com',
            'chromeos/config-internal',
            'build/generated/build_metadata.jsonproto',
            host_input_path,
            test_output_message=self.test_api.build_metadata_list(),
        )

        flat_config_list_path = self._download_config_pb(
            'chrome-internal.googlesource.com',
            'chromeos/config-internal',
            'hw_design/generated/flattened.binaryproto',
            host_input_path,
            test_output_message=self.test_api.flat_config_list(),
        )

        dut_attribute_list_path = self._download_config_pb(
            'chromium.googlesource.com',
            'chromiumos/config',
            'generated/dut_attributes.jsonproto',
            host_input_path,
            test_output_message=self.test_api.dut_attribute_list(),
        )

      hw_test_plans_path = self.m.path.join(host_input_path,
                                            'hw_test_plans.jsonproto')

      # A list of tuples, mapping an input flag for testplan to the path to the
      # input file on the host. Some flags, such as '-plan' can be specified
      # multiple times, so use a list of tuples instead of a dict.
      #
      # Note that the same mechanism is used for the output of testplan.
      arg_to_host_path = [
          ('-dutattributes', dut_attribute_list_path),
          ('-buildmetadata', build_metadata_list_path),
          ('-flatconfiglist', flat_config_list_path),
          ('-out', hw_test_plans_path),
      ]

      # Copy each Starlark file to the host input dir, and add to
      # arg_to_host_path.
      for starlark_file in starlark_files:
        basename = self.m.path.basename(starlark_file)
        dest = self.m.path.join(host_input_path, basename)
        self.m.file.copy('copy ' + basename, starlark_file, dest)
        arg_to_host_path.append(('-plan', dest))

      # Build a list of args to pass to docker run. For each (flag, host path)
      # tuple in arg_to_host_path, add args [<flag>, <container path>]
      args = ['generate', '-alsologtostderr', '-v', '2']

      for arg, host_path in arg_to_host_path:
        args.extend([
            arg, '{}/{}'.format(container_input_path,
                                self.m.path.basename(host_path))
        ])

      # Run the docker image. The directory with the input files is mounted to
      # the container.
      self.m.docker.run(
          self._docker_image,
          cmd_args=args,
          dir_mapping=[(host_input_path, container_input_path)],
      )

      # Read the output HWTestPlans, which are readable on the host because
      # of the mounted directory.
      hw_test_plans = []
      output = self.m.file.read_raw(
          'read output ' + hw_test_plans_path, hw_test_plans_path,
          test_data='\n'.join(
              json_format.MessageToJson(rule).replace('\n', '')
              for rule in self.test_api.hw_test_plans()))
      for line in output.splitlines():
        plan = plan_pb2.HWTestPlan()
        json_format.Parse(line, plan)
        hw_test_plans.append(plan)

      return hw_test_plans
