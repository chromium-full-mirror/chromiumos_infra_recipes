# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api

DEFAULT_BUCKET_NAME = 'cros-code-coverage-data'
DEFAULT_CODE_PROJECT = 'chromiumos/platform2'

PUBLIC_CODE_HOST = 'chromium'
BRANCH = 'refs/heads/master'


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
    # The commit id of BRANCH for the project.
    self._commit_id = None

  @property
  def metadata_dir(self):
    """A temporary directory for the metadata.

    Temp dir is created on first access to this property.
    """
    if not self._metadata_dir:
      self._metadata_dir = self.m.path.mkdtemp(prefix='code-coverage')
    return self._metadata_dir

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
    result.presentation.properties['gitiles_commit_ref'] = BRANCH
    result.presentation.properties['gitiles_commit_id'] = self._commit_id

  def process_coverage_data(self, build_target):
    """Processes the coverage data for metadata."""
    with self.m.step.nest('process code coverage data'):
      try:
        self._commit_id = self.m.gitiles.fetch_revision(PUBLIC_CODE_HOST,
                                                        self._project, BRANCH)
        self._generate_and_upload_metadata(build_target)
      except:  # pylint: disable=bare-except
        self.m.step.active_result.presentation.properties[
            'process_coverage_data_failure'] = True
        raise

    self._set_builder_output_properties_for_uploads()

  def _compose_gs_path_for_coverage_data(self, data_type):
    build = self.m.buildbucket.build
    if build.input.gerrit_changes:
      raise recipe_api.StepFailure(
          'gerrit changes and cq builds are not yet supported')
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
    args = [
        '--chroot-dir',
        self.m.cros_sdk.chroot.path,
        '--checkout-dir',
        self.m.cros_source.workspace_path,
        '--project-dir',
        self.m.cros_source.find_project_paths(self._project, BRANCH)[0],
        '--output-dir',
        self.metadata_dir,
        '--build-target',
        build_target.name,
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
