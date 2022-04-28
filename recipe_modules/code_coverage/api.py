# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import copy
from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure

class CoverageFileSettings(object):
  """Contains parameters used to drive different coverage upload workflows."""

  def __init__(self, should_clean, filter_llvm_json_coverage_to_cl_files):
    self.should_clean = should_clean
    self.filter_llvm_json_coverage_to_cl_files = filter_llvm_json_coverage_to_cl_files


DEFAULT_CODE_PROJECT = 'chromiumos/platform2'
DEFAULT_CODE_BRANCH = 'refs/heads/main'
PUBLIC_CODE_HOST = 'chromium'
CODESEARCH_PROJECT = 'chromiumos/codesearch'
DEFAULT_BUCKET_NAME = 'cros-code-coverage-data'
# TODO(b/222328534): Use autopush as default value instead.
DEFAULT_COVERAGE_ENV = 'prod'

# TODO(b/189356506): Remove experimental path after auto deploy is implemented.
INCREMENTAL_COVERAGE_CIPD_PACKAGE = 'experimental/chromiumos/infra/code_coverage/manual/incremental_code_coverage'
INCREMENTAL_COVERAGE_CIPD_VERSION = 'incremental_code_coverage:353038870'
INCREMENTAL_COVERAGE_CIPD_FILE = 'incremental_code_coverage'

ABSOLUTE_COVERAGE_CIPD_PACKAGE = 'experimental/chromiumos/infra/code_coverage/manual/absolute_code_coverage'
ABSOLUTE_COVERAGE_CIPD_VERSION = 'absolute_code_coverage:362552734'
ABSOLUTE_COVERAGE_CIPD_FILE = 'absolute_code_coverage'


class CodeCoverageApi(recipe_api.RecipeApi):
  """This module contains apis to generate code coverage data."""

  def __init__(self, props, *args, **kwargs):
    super(CodeCoverageApi, self).__init__(*args, **kwargs)
    # Temp dir for metadata.
    self._metadata_dir = None
    # The bucket to which code coverage data should be uploaded.
    self._gs_bucket = props.gs_bucket or DEFAULT_BUCKET_NAME
    # TODO(b/187795079) and b(184035226). Currently only required for cleanup and chromium coverage which will go away after directory coverage is enabled.
    # The project that contains the code this coverage data is being generated for.
    # The project should be visible on https://chromium.googlesource.com/.
    self._project = props.project or DEFAULT_CODE_PROJECT
    # The env to upload results to.
    self._coverage_env = props.coverage_env or DEFAULT_COVERAGE_ENV
    # The branch this coverage data is being generated for.
    self._branch = props.branch or DEFAULT_CODE_BRANCH
    # Whether we need to skip chromium coverage upload.
    self._skip_chromium_upload = props.skip_chromium_upload or False
    # Path to incremental coverage client.
    self._incremental_coverage_tool = None
    # Path to absolute coverage client.
    self._absolute_coverage_tool = None

  @property
  def metadata_dir(self):
    """A temporary directory for the metadata.

    Temp dir is created on first access to this property.
    """
    if not self._metadata_dir:
      self._metadata_dir = self.m.path.mkdtemp(prefix='code-coverage')
    return self._metadata_dir

  @property
  def _code_coverage_root(self):
    return self.m.path['start_dir'].join('code_coverage')

  def upload_firmware_lcov(
      self, build_target_name, tarfile,
      step_name='upload code coverage data (firmware lcov)'):
    """Uploads firmware lcov code coverage.

      Args:
        build_target_name (str): name of the build target.
        tarfile (Path): path to tarfile.
        step_name (str): name for the step.
    """
    self.process_coverage_data(build_target_name, tarfile, 'LCOV', step_name,
                               CoverageFileSettings(False, False))

  def upload_code_coverage_llvm_json(
      self, build_target_name, tarfile,
      step_name='upload code coverage data (code coverage llvm json)'):
    """Uploads code coverage llvm json.

      Args:
        build_target_name (str): name of the build target.
        tarfile (Path): path to tarfile.
        step_name (str): name for the step.
    """
    # Settings for capturing incremental coverage.
    incremental_settings = CoverageFileSettings(True, True)
    # Settings for capturing absolute coverage.
    absolute_settings = CoverageFileSettings(True, False)
    # Settings for capturing absolute coverage on Chromium dashboard.
    absolute_chromium_settings = CoverageFileSettings(False, False)

    self.process_coverage_data(build_target_name, tarfile, 'LLVM', step_name,
                               incremental_settings, absolute_settings,
                               absolute_chromium_settings)

  def process_coverage_data(self, build_target_name, tarfile, coverage_type,
                            step_name='upload code coverage data',
                            incremental_settings=None,
                            absolute_cs_settings=None,
                            absolute_chromium_settings=None):
    """Uploads code coverage data to the requested external sources.

      Args:
        build_target_name (str): name of the build target.
        tarfile (Path): path to tarfile.
        coverage_type (str): type of coverage being uploaded (LCOV, or LLVM).
        step_name (str): name for the step.
        incremental_settings (CoverageFileSettings): settings for uploading coverage to gerrit.
        absolute_cs_settings (CoverageFileSettings): settings for uploading coverage to code search.
        absolute_chromium_settings (CoverageFileSettings): settings for uploading coverage to chromium.
    """
    with self.m.step.nest(step_name):
      try:
        self._ensure_binaries()

        workdir = self.m.path.mkdtemp(prefix='ccov-upload')
        with self.m.context(cwd=workdir):
          path_to_extracted_files = workdir.join('out')
          self.m.archive.extract(
              'untar {}'.format(self.m.path.basename(tarfile)),
              archive_file=str(tarfile), output=path_to_extracted_files)
          for coverage_file in self.m.file.listdir(
              'listdir', path_to_extracted_files, test_data=('coverage.json',)):
            self._upload_incremental_coverage_to_gerrit(coverage_file,
                                                        coverage_type,
                                                        build_target_name,
                                                        incremental_settings)
            self._upload_absolute_coverage_to_code_search(
                coverage_file, coverage_type, build_target_name,
                absolute_cs_settings)
            self._upload_absolute_coverage_to_chromium_coverage(
                coverage_file, build_target_name, self._project,
                absolute_chromium_settings)
      except StepFailure:
        self.m.step.active_result.presentation.properties[
            'process_coverage_data_failure'] = True

  def _ensure_binaries(self):
    """Ensure this module's binaries are installed."""
    if not self._incremental_coverage_tool:
      with self.m.step.nest('ensure binaries'):
        with self.m.context(infra_steps=True):
          pkgs = self.m.cipd.EnsureFile()
          pkgs.add_package(INCREMENTAL_COVERAGE_CIPD_PACKAGE,
                           INCREMENTAL_COVERAGE_CIPD_VERSION)
          pkgs.add_package(ABSOLUTE_COVERAGE_CIPD_PACKAGE,
                           ABSOLUTE_COVERAGE_CIPD_VERSION)
          self.m.cipd.ensure(self._code_coverage_root, pkgs)

          self._incremental_coverage_tool = self._code_coverage_root.join(
              INCREMENTAL_COVERAGE_CIPD_FILE)
          self._absolute_coverage_tool = self._code_coverage_root.join(
              ABSOLUTE_COVERAGE_CIPD_FILE)

  def _write_cleaned_coverage_file(self, path_to_coverage_file,
                                   build_target_name, coverage_file_setting):
    # Nothing to do if there are no settings.
    if coverage_file_setting.should_clean is False:
      return path_to_coverage_file

    tmp_dir = self.m.path.mkdtemp(prefix='cleaned-coverage')
    cleaned_path_file = tmp_dir.join('cleaned.file')
    self.m.python(
        'writing cleaned coverage file',
        self.resource('clean_coverage_file.py'), args=[
            '--coverage-file',
            path_to_coverage_file,
            '--constants-file',
            self.resource('constants.json'),
            '--output-file',
            cleaned_path_file,
            '--build-target',
            build_target_name,
        ], venv=True)

    # Read the file and include it in the log for debugging purposes.
    self.m.file.read_text('read cleaned.file', cleaned_path_file,
                          include_log=True)

    # Exit if the file does not need to be filtered.
    if not coverage_file_setting.filter_llvm_json_coverage_to_cl_files:
      return cleaned_path_file

    # Filter the data to the changed files.
    with self.m.step.nest('filter to changed files only') as presentation:
      # Get the names of all the files in each cl.
      patch_set_file_names = {}
      with self.m.step.nest('get patch sets'):
        patch_sets = [
            self.m.gerrit.fetch_patch_set_from_change(commit,
                                                      include_files=True)
            for commit in self.m.cros_infra_config.gerrit_changes
        ]

        for patch_set in patch_sets:
          for f in patch_set.file_infos.keys():
            patch_set_file_names[f.strip().lower()] = True

      # Write out the changed file names for debugging.
      presentation.logs['output'] = [str(patch_set_file_names.keys())]
      presentation.step_text = 'found %d file changes.' % len(
          patch_set_file_names.keys())

      # Rewrite the coverage llvm json file to only include the files from the cls.
      data_to_clean = self.m.file.read_json(
          'read coverage data from {}'.format(cleaned_path_file),
          cleaned_path_file, test_data={
              'data': [{
                  'files': [{
                      'filename': 'my/fake/file',
                  }, {
                      'filename': 'a_random/file.cc'
                  }]
              }],
              'type': 'coverage',
              'version': '0.0',
          })

      coverage_data = []
      for data in data_to_clean['data']:
        for file_data in data['files']:

          for patch_file_name in patch_set_file_names:
            # file_data[filename] contains src prefix example: /src/platform2/vm/foo.cc.
            # patch_file_name does not contain src prefix. example: vm/foo.cc.
            # So perform filtering based on endswith check.
            if file_data['filename'].strip().lower().endswith(patch_file_name):
              # Zoss expects filename without src prefix. So update file_data
              # filename
              file_data_copy = copy.deepcopy(file_data)
              file_data_copy['filename'] = patch_file_name
              coverage_data.append(file_data_copy)

      # Write out the results and return the path to the filtered file.
      cleaned_and_filtered_path_file = tmp_dir.join('cleaned_and_filtered.file')
      self.m.file.write_json(
          'write cleaned and filtered file', cleaned_and_filtered_path_file, {
              'data': [{
                  'files': coverage_data
              }],
              'type': data_to_clean['type'],
              'version': data_to_clean['version'],
          }, include_log=True)

      return cleaned_and_filtered_path_file

  def _upload_absolute_coverage_to_code_search(self, fpath, coverage_type,
                                               build_target_name,
                                               absolute_cs_settings):
    """Uploads the coverage data to code search.

      Args:
        fpath (str): path to the coverage file.
        coverage_type (str): type of coverage being uploaded (LCOV, or LLVM).
        build_target_name (str): name of the build target.
        absolute_cs_settings (CoverageFileSettings): settings for uploading coverage.
    """
    if self.m.cq.active or absolute_cs_settings is None:
      return

    with self.m.step.nest('upload absolute coverage to Code Search'):
      absolute_coverage_file = self._write_cleaned_coverage_file(
          fpath, build_target_name, absolute_cs_settings)

      codesearch_commit_id = self.m.gitiles.fetch_revision(
          PUBLIC_CODE_HOST, CODESEARCH_PROJECT, self._branch)
      build = self.m.buildbucket.build

      self.m.step(
          'absolute coverage upload for {}'.format(fpath),
          [
              'luci-auth',
              'context',
              '--',
              self._absolute_coverage_tool,
              '--absolute_coverage_service_env',
              self._coverage_env,
              '--timeout',
              '10m',
              '--host',
              PUBLIC_CODE_HOST,
              '--project',
              CODESEARCH_PROJECT,
              '--commit_id',
              codesearch_commit_id,
              '--ref',
              # self._branch,
              # TODO(b/189193947): must be master for code search integration.
              'refs/heads/master',
              '--uploader_name',
              build.builder.builder,
              '--uploader_id',
              codesearch_commit_id + '_' + str(build.id),
              '--format',
              coverage_type,
              '--coverage_file',
              str(absolute_coverage_file),
          ])

  def _upload_incremental_coverage_to_gerrit(self, fpath, coverage_type,
                                             build_target_name,
                                             incremental_settings):
    """Uploads the coverage data to gerrit.

      Args:
        fpath (str): path to the coverage file.
        coverage_type (str): type of coverage being uploaded (LCOV, or LLVM).
        build_target_name (str): name of the build target.
        incremental_settings (CoverageFileSettings): settings for uploading coverage.
    """
    if not self.m.cq.active or incremental_settings is None:
      return

    with self.m.step.nest('upload incremental coverage to gerrit'):
      incremental_coverage_file = self._write_cleaned_coverage_file(
          fpath, build_target_name, incremental_settings)

      for change in self.m.cros_infra_config.gerrit_changes:
        self.m.step(
            'upload {} for {} (ps #{})'.format(
                self.m.path.basename(fpath), change.change, change.patchset),
            wrapper=['luci-auth', 'context', '--'],
            cmd=[
                self._incremental_coverage_tool,
                '--env',
                self._coverage_env,
                '--host',
                change.host,
                '--project',
                change.project,
                '--change_id',
                change.change,
                '--patchset',
                change.patchset,
                '--uploader_name',
                self.m.buildbucket.build.builder.builder,
                '--uploader_id',
                '{}_{}_{}'.format(change.change, change.patchset,
                                  str(self.m.buildbucket.build.id)),
                '--format',
                coverage_type,
                '--coverage_file',
                str(incremental_coverage_file),
            ],
            stdout=self.m.raw_io.output(add_output_log=True),
            stderr=self.m.raw_io.output(add_output_log=True),
        )

  def _compose_gs_path_for_chromium_coverage(self, data_type):
    build = self.m.buildbucket.build
    commit = build.input.gitiles_commit
    return 'postsubmit/%s/%s/%s/%s/%s/%s/%s' % (
        commit.host,
        commit.project,
        commit.id,  # A commit HEX SHA1 is unique in a Gitiles project.
        build.builder.bucket,
        build.builder.builder,
        build.id,
        data_type,
    )

  def _upload_absolute_coverage_to_chromium_coverage(
      self, fpath, build_target_name, project_name_to_use,
      absolute_chromium_settings):
    """Uploads the coverage data to chromium coverage.

      Args:
        fpath (str): path to the coverage file.
        build_target_name (str): name of the build target.
        project_name_to_use (str): name of the project.
        absolute_chromium_settings (CoverageFileSettings): settings for uploading coverage.
    """
    if self.m.cq.active or absolute_chromium_settings is None:
      return

    # Do not update coverage information of asked to skip.
    if self._skip_chromium_upload:
      return

    # Do not update coverage information for non-prod envs.
    if self._coverage_env.lower() != 'prod':
      return

    with self.m.step.nest('upload absolute coverage to chromium coverage'):
      commit_id = self.m.gitiles.fetch_revision(PUBLIC_CODE_HOST,
                                                project_name_to_use,
                                                self._branch)

      path_to_coverage_file = self._write_cleaned_coverage_file(
          fpath, build_target_name, absolute_chromium_settings)

      self.m.python(
          'converting metadata for test coverage',
          self.resource('convert_coverage_metadata_from_llvm.py'), args=[
              '--checkout-dir',
              self.m.cros_source.workspace_path,
              '--project-dir',
              self.m.cros_source.find_project_paths(project_name_to_use,
                                                    self._branch)[0],
              '--output-dir',
              self.metadata_dir,
              '--constants-file',
              self.resource('constants.json'),
              '--path-to-coverage-file',
              path_to_coverage_file,
              '--build-target',
              build_target_name,
          ], venv=True)

      gs_path = self._compose_gs_path_for_chromium_coverage('metadata')
      upload_step = self.m.gsutil.upload(self.metadata_dir, self._gs_bucket,
                                         gs_path, link_name=None, args=['-r'],
                                         multithreaded=True,
                                         name='upload coverage metadata')
      upload_step.presentation.links['metadata report'] = (
          'https://storage.cloud.google.com/%s/%s/index.html' %
          (self._gs_bucket, gs_path))

      # Set the output properties
      result = self.m.step('Set builder output properties', None)
      result.presentation.properties['coverage_metadata_gs_paths'] = [gs_path]
      result.presentation.properties['mimic_builder_names'] = [
          self.m.buildbucket.build.builder.builder
      ]
      result.presentation.properties['coverage_gs_bucket'] = self._gs_bucket
      result.presentation.properties['coverage_is_presubmit'] = False

      # Override the default parameters so that code coverage processor knows where
      # to look for the code. This location needs to be public.
      result.presentation.properties['coverage_override_gitiles_commit'] = True
      result.presentation.properties[
          'gitiles_commit_host'] = PUBLIC_CODE_HOST + '.googlesource.com'
      result.presentation.properties[
          'gitiles_commit_project'] = project_name_to_use
      result.presentation.properties['gitiles_commit_ref'] = self._branch
      result.presentation.properties['gitiles_commit_id'] = commit_id
