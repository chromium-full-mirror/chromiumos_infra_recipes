# -*- coding: utf-8 -*-

# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api
from recipe_engine.util import exponential_retry

import email.utils
import time


class MetadataJsonApi(recipe_api.RecipeApi):
  """A module to write metadata.json into GS for GoldenEye consumption."""

  def __init__(self, *args, **kwargs):
    super(MetadataJsonApi, self).__init__(*args, **kwargs)
    self._metadata = {}
    self._add_defunct_entries()

  def _add_defunct_entries(self):
    """These fields are no longer available."""
    self._metadata['build-number'] = 0
    self._metadata['build_id'] = 0
    self._metadata['board-metadata'] = {}
    self._metadata['master_build_id'] = 0
    self._metadata['metadata-version'] = '2'
    self._metadata['child-configs'] = []

  def _print_time(self, time_secs, test_data=None):
    if self._test_data.enabled:
      return test_data
    # Developer workstations, cloudtop and GCE machines have different
    # timezones. Just skip testing this code.
    return '{} ({})'.format(
        email.utils.formatdate(timeval=time_secs, localtime=True),
        time.strftime('%Z', time.localtime(time_secs)))  # pragma: nocover

  def add_default_entries(self):
    """These fields are available at the start of the build."""
    build = self.m.buildbucket.build
    self._metadata['buildbucket_id'] = build.id
    builder_name = build.builder.builder
    self._metadata['builder-name'] = builder_name
    self._metadata['bot-config'] = builder_name
    # For now consider builder_type = bucket.
    self._metadata['builder_type'] = build.builder.bucket
    # Branch is always master for now.
    self._metadata['branch'] = 'master'

    self._metadata['time'] = {
        'start':
            self._print_time(build.start_time.seconds,
                             test_data='some start time')
    }

    build_target = self.m.cros_history.get_build_target(build)
    self._metadata['boards'] = [build_target]
    config = self.m.cros_infra_config.get_builder_config(builder_name)
    self._metadata['unibuild'] = config.general.unibuild

    for dimension in build.infra.swarming.bot_dimensions:  # pragma: nocover
      if dimension.key == 'id':
        self._metadata['bot-hostname'] = dimension.value

  def add_version_entries(self, version_dict):
    """Update metadata with version info.

    Args:
      version_dict(dict): Map containing version info.
    """
    self._metadata['version'] = {
        'chrome': version_dict.get('chromeVersion', ''),
        'full': version_dict.get('fullVersion', ''),
        'milestone': version_dict.get('milestoneVersion', ''),
        'platform': version_dict.get('platformVersion', ''),
    }

  def get_metadata(self):
    """Get the metadata dict. Should only be used for unittesting.

    Returns: dict, metadata info.
    """
    return self._metadata

  def write_to_file(self, filename):
    """Write metadata dict to a tempfile.

    Args:
      filename(str): Filename to write to.

    Returns:
      str, path to the file written.
    """
    temp_dir = self.m.path.mkdtemp(prefix='metadata')
    file_path = temp_dir.join(filename)
    self.m.file.write_json('writing '.join(filename), file_path, self._metadata,
                           indent=4)
    return str(file_path)

  def upload_to_gs(self, gs_bucket, config, build_target, partial=False):
    """Upload metadata to GS at its current state.

    Args:
      gs_bucket (str): Google storage bucket to upload artifacts to.
      config(BuilderConfig): builder config of this builder.
      target (BuildTarget): The build target of this builder.
      partial(bool): whether the metadata is incomplete.
    """
    with self.m.step.nest('upload metadata') as presentation:
      filename = 'partial_metadata.json' if partial else 'metadata.json'
      file_path = self.write_to_file(filename)
      gs_path = self.m.cros_artifacts.artifacts_gs_path(
          config.id.name, build_target, config.id.type)
      upload_uri = 'gs://{}/{}/{}'.format(gs_bucket, gs_path, filename)
      self._upload(file_path, upload_uri)
      presentation.links['gs_link'] = self.m.urls.get_gs_path_url(upload_uri)

  @exponential_retry(retries=3, condition=lambda e: e.had_timeout)
  def _upload(self, source, dest):
    self.m.gsutil(['cp', source, dest], timeout=10 * 60)
