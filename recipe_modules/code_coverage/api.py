# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure

import os
import re

DEFAULT_BUCKET_NAME = 'cros-code-coverage-data'
DEFAULT_CODE_PROJECT = 'chromiumos/platform2'
DEFAULT_CODE_BRANCH = 'refs/heads/main'

PUBLIC_CODE_HOST = 'chromium'
CODESEARCH_PROJECT = 'chromiumos/codesearch'


class CodeCoverageApi(recipe_api.RecipeApi):
  """This module contains apis to generate code coverage data."""

  def __init__(self, props, *args, **kwargs):
    super(CodeCoverageApi, self).__init__(*args, **kwargs)
    # Temp dir for metadata
    self._metadata_dir = None
    # The list of coverage metadata gs paths to be uploaded.
    self._coverage_metadata_gs_paths = []
    # The bucket to which code coverage data should be uploaded.
    self._gs_bucket = props.gs_bucket or DEFAULT_BUCKET_NAME
    # The project that contains the code this coverage data is being generated for.
    self._project = props.project or DEFAULT_CODE_PROJECT
    # The branch this coverage data is being generated for.
    self._branch = props.branch or DEFAULT_CODE_BRANCH
    # The commit id of branch for the project.
    self._commit_id = None
    # Temp dir for zoss
    self._zoss_dir = None

  @property
  def metadata_dir(self):
    """A temporary directory for the metadata.

    Temp dir is created on first access to this property.
    """
    if not self._metadata_dir:
      self._metadata_dir = self.m.path.mkdtemp(prefix='code-coverage')
    return self._metadata_dir

  @property
  def zoss_dir(self):
    """A temporary directory for the zoss coverage data.

    Temp dir is created on first access to this property.
    """
    if not self._zoss_dir:
      self._zoss_dir = self.m.path.mkdtemp(prefix='code-coverage-zoss')
    return self._zoss_dir

  def _set_builder_output_properties_for_uploads(self):
    """Sets the output property of the builder."""
    result = self.m.python.succeeding_step('Set builder output properties', '')
    result.presentation.properties['coverage_metadata_gs_paths'] = (
        self._coverage_metadata_gs_paths)
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
    result.presentation.properties['gitiles_commit_project'] = self._project
    result.presentation.properties['gitiles_commit_ref'] = self._branch
    result.presentation.properties['gitiles_commit_id'] = self._commit_id

  def process_coverage_data(self, build_target):
    """Processes the coverage data for metadata."""
    with self.m.step.nest('process code coverage data'):
      try:
        self._commit_id = self.m.gitiles.fetch_revision(PUBLIC_CODE_HOST,
                                                        self._project,
                                                        self._branch)
        with self.m.step.nest('upload coverage to ZOSS'):
          self._upload_to_zoss(build_target)
        with self.m.step.nest('upload coverage to chromium coverage'):
          self._generate_and_upload_metadata(build_target)
      except StepFailure:
        self.m.step.active_result.presentation.properties[
            'process_coverage_data_failure'] = True
        raise

    self._set_builder_output_properties_for_uploads()

  def _compose_gs_path_for_coverage_data(self, data_type):
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

  def _generate_and_upload_metadata(self, build_target):
    """Generates the coverage info in metadata format."""
    # The old coverage service does not support gerrit changes.
    # Just skip it if there are gerrit changes.
    if self.m.buildbucket.build.input.gerrit_changes:
      return

    args = [
        '--chroot-dir',
        self.m.cros_sdk.chroot.path,
        '--checkout-dir',
        self.m.cros_source.workspace_path,
        '--project-dir',
        self.m.cros_source.find_project_paths(self._project, self._branch)[0],
        '--output-dir',
        self.metadata_dir,
        '--constants-file',
        self.resource('constants.json'),
        '--build-target',
        build_target.name,
        '--project-name',
        self._project,
    ]

    try:
      self.m.python('converting metadata for test coverage',
                    self.resource('convert_coverage_metadata_from_llvm.py'),
                    args=args, venv=True)
    finally:
      gs_path = self._compose_gs_path_for_coverage_data('metadata')
      upload_step = self.m.gsutil.upload(self.metadata_dir, self._gs_bucket,
                                         gs_path, link_name=None, args=['-r'],
                                         multithreaded=True,
                                         name='upload coverage metadata')
      upload_step.presentation.links['metadata report'] = (
          'https://storage.cloud.google.com/%s/%s/index.html' %
          (self._gs_bucket, gs_path))
      self._coverage_metadata_gs_paths.append(gs_path)

  def _upload_to_zoss(self, build_target):
    """Cleans up the coverage results and uploads them to ZOSS."""
    # For now skip this in CQ.
    if self.m.buildbucket.build.input.gerrit_changes:
      return

    coverage_path = self.m.path.abs_to_path(self.m.cros_sdk.chroot.path).join(
        'build', build_target.name, 'build', 'coverage_data')

    coverage_files = self.m.file.glob_paths('find coverage files',
                                            coverage_path, '**/coverage.json',
                                            test_data=['coverage.json'])

    constants = self.m.file.read_json(
        'read constants', self.resource('constants.json'), test_data={
            'chromiumos/platform2': [{
                'prefix': 'base-[^/]*/base',
                'src_path': 'base'
            }]
        })
    coverage_type = ''
    coverage_version = ''
    coverage_data = []
    for coverage_file in coverage_files:
      try:
        data = self.m.file.read_json(
            'read coverage data from {}'.format(coverage_file), coverage_file,
            test_data={
                'data': [{
                    'files': [{
                        'filename': '/build/amd64-generic/base-0/base/test.cc'
                    }]
                }],
                'type': 'coverage',
                'version': '0.0',
            })
      except StepFailure:
        # Ignore bad json files.
        continue
      coverage_type = data['type']
      coverage_version = data['version']
      for datum in data['data']:
        for file_data in datum['files']:
          filename = file_data['filename']
          coverage_path = os.path.normpath(filename)
          for mapping in constants[self._project]:
            pre = os.path.join('/build', build_target.name, mapping['prefix'])
            if re.match(pre, filename):
              coverage_path = re.sub(pre, mapping['src_path'], coverage_path)
              # Hard-coded /src/platform2 is a temporary work around
              # while we still use the old service.
              # We currently load the same file remapper used by the old service
              # which is relative to the platform2 folder.
              file_data['filename'] = '/src/platform2/' + coverage_path
              coverage_data.append(file_data)
              break

    out_file = self.zoss_dir.join('coverage.json')
    self.m.file.write_json(
        'write processed coverage json', out_file, {
            'data': [{
                'files': coverage_data
            }],
            'type': coverage_type,
            'version': coverage_version,
        })

    # ZOSS always submits coverage data to the codesearch project.
    codesearch_commit_id = self.m.gitiles.fetch_revision(
        PUBLIC_CODE_HOST, CODESEARCH_PROJECT, self._branch)
    build = self.m.buildbucket.build
    self.m.step('absolute coverage upload for {}'.format(out_file), [
        'luci-auth',
        'context',
        '--',
        self.resource('vomfass_llvm_cloud_uploader'),
        '--vomfass_service_addr',
        'bifrost-vomfassupdateservice-c2p.googleapis.com',
        '--timeout',
        '10m',
        '--host',
        PUBLIC_CODE_HOST,
        '--project',
        CODESEARCH_PROJECT,
        '--commit_id',
        codesearch_commit_id,
        '--ref',
        self._branch,
        '--uploader_name',
        build.builder.builder,
        '--uploader_id',
        codesearch_commit_id + '_' + str(build.id),
        '--llvm_json_file',
        out_file,
    ])
