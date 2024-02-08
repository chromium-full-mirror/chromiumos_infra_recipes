# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe definition for code coverage recipe."""

import copy
import json
import os
from datetime import datetime
from pathlib import Path

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure


class CoverageFileSettings:
  """Contains parameters used to drive different coverage upload workflows."""

  def __init__(self, should_clean, to_absolute_path):
    self.should_clean = should_clean
    self.to_absolute_path = to_absolute_path


DEFAULT_CODE_PROJECT = 'chromiumos/platform2'
DEFAULT_CODE_BRANCH = 'refs/heads/main'
PUBLIC_CODE_HOST = 'chromium'
CODESEARCH_PROJECT = 'chromiumos/codesearch'
DEFAULT_BUCKET_NAME = 'cros-code-coverage-data'
E2E_COVERAGE_BUCKET_NAME = 'e2e-coverage-artifacts'
E2E_METADATA_FILENAME = 'e2e_metadata.json'
ACTIVE_VERSION_FILENAME = 'current.json'
# Number of seconds in 2w.
ACTIVE_VERSION_DIFF_SECONDS = 1209600
# TODO(b/222328534): Use autopush as default value instead.
DEFAULT_COVERAGE_ENV = 'prod'

# TODO(b/189356506): Remove experimental path after auto deploy is implemented.
PACKAGE_ROOT = 'experimental/chromiumos/infra/code_coverage/manual'
INCREMENTAL_COVERAGE_CIPD_PACKAGE = f'{PACKAGE_ROOT}/incremental_code_coverage'
INCREMENTAL_COVERAGE_CIPD_VERSION = 'incremental_code_coverage:cl600915087'
INCREMENTAL_COVERAGE_CIPD_FILE = 'incremental_code_coverage'

ABSOLUTE_COVERAGE_CIPD_PACKAGE = f'{PACKAGE_ROOT}/absolute_code_coverage'
ABSOLUTE_COVERAGE_CIPD_VERSION = 'absolute_code_coverage:cl600915087'
ABSOLUTE_COVERAGE_CIPD_FILE = 'absolute_code_coverage'

# Number of file coverage entries per chunk
FILE_ENTRIES_PER_CHUNK = 3000


class CodeCoverageApi(recipe_api.RecipeApi):
  """This module contains apis to generate code coverage data."""

  def __init__(self, props, *args, **kwargs):
    super().__init__(*args, **kwargs)
    # Temp dir for metadata.
    self._metadata_dir = None
    # The bucket to which code coverage data should be uploaded.
    self._gs_bucket = props.gs_bucket or DEFAULT_BUCKET_NAME
    # TODO(b/187795079) and b(184035226). Currently only required for cleanup
    # and chromium coverage which will go away after directory coverage is enabled.
    # The project that contains the code this coverage data is being generated for.
    # The project should be visible on https://chromium.googlesource.com/.
    self._project = props.project or DEFAULT_CODE_PROJECT
    # The env to upload results to.
    self._coverage_env = props.coverage_env or DEFAULT_COVERAGE_ENV
    # The branch this coverage data is being generated for.
    self._branch = props.branch or DEFAULT_CODE_BRANCH
    # Whether we need to skip chromium coverage upload.
    self._skip_chromium_upload = props.skip_chromium_upload or False
    # Whether invoked by incremental(CQ) builder.
    self._cq_builder = props.cq_builder
    # Path to incremental coverage client.
    self._incremental_coverage_tool = None
    # Path to absolute coverage client.
    self._absolute_coverage_tool = None
    self._merger_input_incremental_coverage = []
    self._merger_input_absolute_coverage = []

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
      self, tarfile, step_name='upload code coverage data (firmware lcov)'):
    """Uploads firmware lcov code coverage.

      Args:
        tarfile (Path): path to tarfile.
        step_name (str): name for the step.
    """
    self.process_coverage_data(
        tarfile,
        'LCOV',
        step_name=step_name,
        # Filtering only works for llvm json files.
        incremental_settings=CoverageFileSettings(True, False),
        absolute_cs_settings=CoverageFileSettings(True, True),
    )

  def upload_code_coverage(self, tarfile, coverage_type, gs_artifact_bucket,
                           gs_artifact_path,
                           step_name='upload code coverage data'):
    """Uploads code coverage llvm json and golang.

      Args:
        tarfile (Path): path to tarfile.
        step_name (str): name for the step.
        coverage_type (str): type of coverage being uploaded (LCOV, LLVM, or GO_COV).
        gs_artifact_bucket (str): artifact bucket (eg. chromeos-image-archive).
        gs_artifact_path (str): artifact bucket path (eg. builderName/version-builderID).
    """
    # Settings for capturing incremental coverage.
    incremental_settings = CoverageFileSettings(False, False)
    # Settings for capturing absolute coverage.
    absolute_settings = CoverageFileSettings(False, True)
    # Settings for capturing absolute coverage on Chromium dashboard.
    absolute_chromium_settings = CoverageFileSettings(False, True)

    self.process_coverage_data(
        tarfile,
        coverage_type,
        True,
        gs_artifact_bucket,
        gs_artifact_path,
        step_name,
        incremental_settings,
        absolute_settings,
        absolute_chromium_settings,
    )

  def process_coverage_data(
      self, tarfile, coverage_type, merger_flow_enabled=False,
      gs_artifact_bucket=None, gs_artifact_path=None,
      step_name='upload code coverage data', incremental_settings=None,
      absolute_cs_settings=None, absolute_chromium_settings=None):
    """Uploads code coverage data to the requested external sources.

      Args:
        tarfile (Path): path to tarfile.
        coverage_type (str): type of coverage being uploaded (LCOV, LLVM, or GO_COV).
        merger_flow_enabled (bool): whether merger flow is enabled or not.
        gs_artifact_bucket (str): artifact bucket (eg. chromeos-image-archive).
        gs_artifact_path (str): artifact bucket path (eg. builderName/version-builderID).
        step_name (str): name for the step.
        incremental_settings (CoverageFileSettings): incremental coverage settings.
        absolute_cs_settings (CoverageFileSettings): absolute coverage settings.
        absolute_chromium_settings (CoverageFileSettings): absolute chromium coverage settings.
    """
    with self.m.step.nest(step_name):
      try:
        self._ensure_binaries()

        workdir = self.m.path.mkdtemp(prefix='ccov-upload')
        with self.m.context(cwd=workdir):
          path_to_extracted_files = workdir.join('out')
          self.m.archive.extract(
              f'untar {self.m.path.basename(tarfile)}',
              archive_file=str(tarfile),
              output=path_to_extracted_files,
          )

          coverage_files = self.m.file.listdir(
              'listdir',
              path_to_extracted_files,
              test_data=('coverage.json',),
          )

          for coverage_file in coverage_files:
            self._upload_incremental_coverage_to_gerrit(
                coverage_file, coverage_type, incremental_settings,
                gs_artifact_bucket, gs_artifact_path, merger_flow_enabled)
            self._upload_absolute_coverage_to_code_search(
                coverage_file, coverage_type, absolute_cs_settings,
                merger_flow_enabled, gs_artifact_bucket, gs_artifact_path)
            self._upload_absolute_coverage_to_chromium_coverage(
                coverage_file, self._project, absolute_chromium_settings)

          if merger_flow_enabled:
            self._merger_set_properties()
      except StepFailure:
        self.m.step.active_result.presentation.properties[
            'process_coverage_data_failure'] = True

  def _merger_set_properties(self):
    """Sets merger related builder output properties.

      This function adds coverage information in the output properties.
      Coverage information is then used by the code coverage merger to
      process the coverage.
    """
    step = self.m.easy.set_properties_step(
        'Set merger properties',
        merger_incremental_coverage=self._merger_input_incremental_coverage,
        merger_absolute_coverage=self._merger_input_absolute_coverage)
    step.presentation.logs['merger_incremental_coverage'] = '{}'.format(
        self._merger_input_incremental_coverage)
    step.presentation.logs['merger_absolute_coverage'] = '{}'.format(
        self._merger_input_absolute_coverage)

  def _merger_incremental(
      self,
      filtered_coverage_file: str,
      change: GerritChange,
      gs_artifact_bucket: str,
      gs_artifact_path: str,
      coverage_type: str,
  ) -> None:
    """Uploads the coverage data to gcs and sets merger properties.

       This function first upload the coverage.json for the change to chromeos archive bucket
       and then sets the CovPaths property in luci output.
       Merger then uses the CovPaths property to download and process the coverage.

      Args:
        filtered_coverage_file(str): location of coverage file on local disk.
        change (GerritChange): gerrit change.
        gs_artifact_bucket (str): artifact bucket (eg. chromeos-image-archive).
        gs_artifact_path (str): artifact bucket path (eg. builderName/version-builderID).
        coverage_type (str): type of coverage being uploaded (LCOV, or LLVM).
    """
    object_path = os.path.join(gs_artifact_path, 'coverage', str(change.change),
                               '.json')

    upload_step = self.m.gsutil.upload(filtered_coverage_file,
                                       gs_artifact_bucket, object_path)

    path = f'https://storage.cloud.google.com/{gs_artifact_bucket}/{object_path}/index.html'
    upload_step.presentation.links['uploaded report'] = path

    self._merger_input_incremental_coverage.append({
        'CovPaths': [f'gs://{gs_artifact_bucket}/{object_path}'],
        'Host': change.host,
        'Project': change.project,
        'PatchSet': change.patchset,
        'Change': change.change,
        'CovType': coverage_type
    })

  def update_e2e_metadata(self, gs_artifact_bucket: str, gs_artifact_path: str,
                          board: str, version: str) -> None:
    """Uploads metadata needed for e2e coverage.

      Args:
        gs_artifact_bucket (str): artifact bucket (eg. chromeos-image-archive).
        gs_artifact_path (str): artifact bucket path (eg. builderName/version-builderID).
        board: Board used for generating artifacts.
        version: CROS version used to build artifacts.
    """
    gs_path = self.m.path.join('active_version', board, ACTIVE_VERSION_FILENAME)
    with self.m.step.nest('verify active version'):
      path = self.metadata_dir.join(ACTIVE_VERSION_FILENAME)
      self.m.gsutil.download(E2E_COVERAGE_BUCKET_NAME, gs_path, path)
      contents = json.loads(
          self.m.file.read_text(name='read current active version', source=path,
                                test_data='{"date":"2024-02-07"}'))

      if self.upload_active_version(contents['date']):
        step_text = 'upload active version(found date diff)'
        self._upload_metadata(step_text, gs_artifact_bucket, gs_artifact_path,
                              board, version, gs_path)

    # Upload metadata irrespective of active version for this builder.
    today = self.m.time.utcnow().strftime('%m-%d-%Y')
    dest_path = Path('e2e_coverage') / board / version / today / 'metadata.json'
    step_text = 'upload e2e coverage metadata'
    self._upload_metadata(step_text, gs_artifact_bucket, gs_artifact_path,
                          board, version, dest_path)

  def upload_active_version(self, active_date: str):
    """Whether we need to upload active version.

      Args:
        active_date: The date in ISOformat present in uploaded active_version.
    """
    if not active_date:
      return True

    diff = self.m.time.utcnow() - datetime.fromisoformat(active_date)
    if diff.total_seconds() >= ACTIVE_VERSION_DIFF_SECONDS:
      return True
    return False

  def _upload_metadata(self, step_text: str, gs_artifact_bucket: str,
                       gs_artifact_path: str, board: str, version: str,
                       gs_dest_path: str) -> None:
    """Upload active version to be used when running tests.

      Args:
        step_text: Step text to write for description.
        gs_artifact_bucket (str): artifact bucket (eg. chromeos-image-archive).
        gs_artifact_path (str): artifact bucket path (eg. builderName/version-builderID).
        board: Board used for generating artifacts.
        version: CROS version used to build artifacts.
        gs_dest_path: Path inside the E2E bucket to write data to.
    """
    path = os.path.join(str(self.metadata_dir), E2E_METADATA_FILENAME)
    with self.m.step.nest(step_text):
      self.m.step(
          'add e2e coverage metadata',
          [
              'vpython3',
              self.resource('e2e_coverage.py'), '--artifacts-bucket',
              gs_artifact_bucket, '--artifacts-path', gs_artifact_path,
              '--board', board, '--version', version, '--path', path
          ],
      )

      upload_step = self.m.gsutil.upload(path, E2E_COVERAGE_BUCKET_NAME,
                                         gs_dest_path)
      upload_step.presentation.links[
          'uploaded report'] = f'https://storage.cloud.google.com/{E2E_COVERAGE_BUCKET_NAME}/{gs_dest_path}'

  def _merger_absolute(
      self,
      absolute_coverage_file: str,
      codesearch_commit_id: str,
      gs_artifact_bucket: str,
      gs_artifact_path: str,
      coverage_type: str,
  ) -> None:
    """Uploads the coverage data to gcs and sets merger properties.

       This function first upload the coverage.json to chromeos archive bucket
       and then sets the CovPaths property in luci output.
       Merger then uses the CovPaths property to download and process the coverage.

      Args:
        absolute_coverage_file(str): location of coverage file on local disk.
        codesearch_commit_id (str): commit id for absolute cc builder.
        gs_artifact_bucket (str): artifact bucket (eg. chromeos-image-archive).
        gs_artifact_path (str): artifact bucket path (eg. builderName/version-builderID).
        coverage_type (str): type of coverage being uploaded (LCOV, or LLVM).
    """
    object_path = os.path.join(gs_artifact_path, 'coverage',
                               codesearch_commit_id, '.json')
    upload_step = self.m.gsutil.upload(absolute_coverage_file,
                                       gs_artifact_bucket, object_path)

    path = f'https://storage.cloud.google.com/{gs_artifact_bucket}/{object_path}/index.html'
    upload_step.presentation.links['uploaded report'] = path

    self._merger_input_absolute_coverage.append({
        'CovPaths': [f'gs://{gs_artifact_bucket}/{object_path}'],
        'Host': PUBLIC_CODE_HOST,
        'Project': CODESEARCH_PROJECT,
        'Ref': DEFAULT_CODE_BRANCH,
        'CovType': coverage_type,
        'CommitID': codesearch_commit_id
    })

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
                                   coverage_file_setting):
    # Nothing to do if there are no settings.
    if coverage_file_setting.should_clean is False:
      return path_to_coverage_file

    tmp_dir = self.m.path.mkdtemp(prefix='cleaned-coverage')
    cleaned_path_file = tmp_dir.join('cleaned.file')

    self.m.step(
        'writing cleaned coverage file',
        [
            'vpython3',
            self.resource('clean_coverage_file.py'),
            '--coverage-file',
            path_to_coverage_file,
            '--constants-file',
            self.resource('path_mapping.json'),
            '--output-file',
            cleaned_path_file,
            '--to_absolute_path',
            coverage_file_setting.to_absolute_path,
        ],
    )

    # Read the file and include it in the log for debugging purposes.
    self.m.file.read_text('read cleaned.file', cleaned_path_file,
                          include_log=True)
    return cleaned_path_file

  def _filter_coverage_to_cl_files(self, path_to_coverage_file):
    # Filter the data to the changed files.
    with self.m.step.nest('filter to changed files only') as presentation:
      # Get the names of all the files in each cl.
      change_to_file_names = {}
      with self.m.step.nest('get patch sets'):
        for commit in self.m.cros_infra_config.gerrit_changes:
          file_names = []
          patch_set = self.m.gerrit.fetch_patch_set_from_change(
              commit, include_files=True)
          for f in patch_set.file_infos.keys():
            file_names.append(f.strip().lower())
          change_to_file_names[commit.change] = file_names

      # Write out the changed file names for debugging.
      presentation.logs['output'] = json.dumps(change_to_file_names, indent=4)

      # Rewrite the coverage llvm json file to only include the files from the cls.
      data_to_clean = self.m.file.read_json(
          f'read coverage data from {path_to_coverage_file}',
          path_to_coverage_file,
          test_data={
              'data': [{
                  'files': [
                      {
                          'filename': 'my/fake/file',
                      },
                      {
                          'filename': 'a_random/file.cc'
                      },
                  ]
              }],
              'type': 'coverage',
              'version': '0.0',
          },
      )

      tmp_dir = self.m.path.mkdtemp(prefix='filtered-coverage')
      result = {}
      for change, file_names in change_to_file_names.items():
        coverage_data = []
        for data in data_to_clean['data']:
          for file_data in data['files']:
            for change_file_name in file_names:
              # file_data[filename] contains src prefix example: /src/platform2/vm/foo.cc.
              # patch_file_name does not contain src prefix. example: vm/foo.cc.
              # So perform filtering based on endswith check.
              if file_data['filename'].strip().lower().endswith(
                  change_file_name):
                # Zoss expects filename without src prefix. So update file_data
                # filename
                file_data_copy = copy.deepcopy(file_data)
                file_data_copy['filename'] = change_file_name
                coverage_data.append(file_data_copy)

        # Write out the results and return the path to the filtered file.
        filtered_path_file = tmp_dir.join(f'filtered.file.{change}')
        self.m.file.write_json(
            'write filtered file', filtered_path_file, {
                'data': [{
                    'files': coverage_data
                }],
                'type': data_to_clean['type'],
                'version': data_to_clean['version'],
            }, include_log=True)
        result[change] = filtered_path_file

      return result

  def _upload_absolute_coverage_to_code_search(self, fpath, coverage_type,
                                               absolute_cs_settings,
                                               merger_flow_enabled=False,
                                               gs_artifact_bucket=None,
                                               gs_artifact_path=None):
    """Uploads the coverage data to code search.

      Args:
        fpath (str): path to the coverage file.
        coverage_type (str): type of coverage being uploaded (LCOV, or LLVM).
        absolute_cs_settings (CoverageFileSettings): settings for uploading coverage.
        merger_flow_enabled (bool): whether merger flow is enabled or not.
        gs_artifact_bucket (str): artifact bucket (eg. chromeos-image-archive).
        gs_artifact_path (str): artifact bucket path (eg. builderName/version-builderID).
    """
    if self._cq_builder or self.m.cq.active or absolute_cs_settings is None:
      return

    with self.m.step.nest(
        'upload absolute coverage to Code Search') as presentation:
      absolute_coverage_file = self._write_cleaned_coverage_file(
          fpath, absolute_cs_settings)

      codesearch_commit_id = self.m.gitiles.fetch_revision(
          PUBLIC_CODE_HOST, CODESEARCH_PROJECT, self._branch)
      if merger_flow_enabled:
        self._merger_absolute(absolute_coverage_file, codesearch_commit_id,
                              gs_artifact_bucket, gs_artifact_path,
                              coverage_type)
      else:
        build = self.m.buildbucket.build
        chunks_file = self._chunk_coverage_file(absolute_coverage_file,
                                                coverage_type)
        presentation.logs['chunked_files'] = str(chunks_file)

        for chunk_file in chunks_file:
          self.m.step(
              f'absolute coverage upload for {fpath}',
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
                  # TODO(b/189193947): must be main for code search integration.
                  DEFAULT_CODE_BRANCH,
                  '--uploader_name',
                  build.builder.builder,
                  '--uploader_id',
                  codesearch_commit_id + '_' + str(build.id),
                  '--format',
                  coverage_type,
                  '--coverage_file',
                  str(chunk_file),
              ])

  def _upload_incremental_coverage_to_gerrit(self, fpath, coverage_type,
                                             incremental_settings,
                                             gs_artifact_bucket,
                                             gs_artifact_path,
                                             merger_flow_enabled=False):
    """Uploads the coverage data to gerrit.

      Args:
        fpath (str): path to the coverage file.
        coverage_type (str): type of coverage being uploaded (LCOV, or LLVM).
        incremental_settings (CoverageFileSettings): settings for uploading coverage.
        gs_artifact_bucket (str): artifact bucket (eg. chromeos-image-archive).
        gs_artifact_path (str): artifact bucket path (eg. builderName/version-builderID).
        merger_flow_enabled (bool): whether merger flow is enabled or not.
    """
    if incremental_settings is None:
      return

    # Make sure we are triggered by the CQ builder.
    if not (self._cq_builder or self.m.cq.active):
      return

    with self.m.step.nest('upload incremental coverage to gerrit'):
      incremental_coverage_file = self._write_cleaned_coverage_file(
          fpath, incremental_settings)

      if merger_flow_enabled:
        change_to_filtered_coverage = self._filter_coverage_to_cl_files(
            incremental_coverage_file)
        for change in self.m.cros_infra_config.gerrit_changes:
          if change.change in change_to_filtered_coverage:
            self._merger_incremental(change_to_filtered_coverage[change.change],
                                     change, gs_artifact_bucket,
                                     gs_artifact_path, coverage_type)
      else:
        for change in self.m.cros_infra_config.gerrit_changes:
          self._invoke_incremental_coverage_tool(incremental_coverage_file,
                                                 change, coverage_type)

  def _invoke_incremental_coverage_tool(self, path, change, coverage_type):
    self.m.step(
        f'upload {self.m.path.basename(path)} for {change.change} (ps #{change.patchset})',
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
            f'{change.change}_{change.patchset}_{str(self.m.buildbucket.build.id)}',
            '--format',
            coverage_type,
            '--coverage_file',
            str(path),
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
      self, fpath, project_name_to_use, absolute_chromium_settings):
    """Uploads the coverage data to chromium coverage.

      Args:
        fpath (str): path to the coverage file.
        project_name_to_use (str): name of the project.
        absolute_chromium_settings (CoverageFileSettings): settings for uploading coverage.
    """
    if self._cq_builder or self.m.cq.active or absolute_chromium_settings is None:
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
          fpath, absolute_chromium_settings)

      self.m.step('converting metadata for test coverage', [
          'vpython3',
          self.resource('convert_coverage_metadata_from_llvm.py'),
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
      ])

      gs_path = self._compose_gs_path_for_chromium_coverage('metadata')
      upload_step = self.m.gsutil.upload(self.metadata_dir, self._gs_bucket,
                                         gs_path, link_name=None, args=['-r'],
                                         multithreaded=True,
                                         name='upload coverage metadata')
      path = f'https://storage.cloud.google.com/{self._gs_bucket}/{gs_path}/index.html'
      upload_step.presentation.links['metadata report'] = path

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

  def _chunk_coverage_file(self, coverage_file, coverage_type):
    """Splits large |coverage_file| into smaller files.

    Method to split coverage |coverage_file| into smaller files,
    each containing |chunk_size| coverage records.

    Args:
      coverage_file (str): Path of the coverage file to be chunked.
      coverage_type (str): Type of coverage.

    Returns:
        Absolute paths of the chunked files.
    """
    dest_dir = self.m.path.mkdtemp(prefix='chunked')
    self.m.step('Chunking coverage file', [
        'vpython3',
        self.resource('chunk_coverage_file.py'),
        '--coverage-file',
        coverage_file,
        '--coverage-type',
        coverage_type,
        '--file-entries-per-chunk',
        FILE_ENTRIES_PER_CHUNK,
        '--chunk-dest-dir',
        str(dest_dir),
    ])

    result = []
    for f in self.m.file.listdir('listdir', dest_dir,
                                 test_data=('coverage.json',)):
      result.append(str(f))

    return result
