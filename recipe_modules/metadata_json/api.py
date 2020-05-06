# -*- coding: utf-8 -*-

# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import step as step_pb2
from google.protobuf import timestamp_pb2

from recipe_engine import recipe_api
from recipe_engine.util import exponential_retry

import contextlib
import datetime
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

  def _safe_buildbucket_get_self(self):
    # If a led job, use a random id.
    if self.m.led.run_id:  # pragma: nocover
      build_id = 8882749049375545216
    else:
      build_id = self.m.buildbucket.build.id

    return self.m.buildbucket.get(build_id)

  def add_default_entries(self):
    """These fields are available at the start of the build."""
    build = self._safe_buildbucket_get_self()
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
    self.m.file.write_json('writing ' + filename, file_path, self._metadata,
                           indent=4)
    return str(file_path)

  def upload_to_gs(self, config, build_target, partial=False):
    """Upload metadata to GS at its current state.

    Args:
      config(BuilderConfig): builder config of this builder.
      target (BuildTarget): The build target of this builder.
      partial(bool): whether the metadata is incomplete.
    """
    with self.m.step.nest('upload metadata') as presentation:
      filename = 'partial_metadata.json' if partial else 'metadata.json'
      file_path = self.write_to_file(filename)
      gs_bucket = config.artifacts.artifacts_gs_bucket
      try:
        gs_path = self.m.cros_artifacts.artifacts_gs_path(
            config.id.name, build_target, config.id.type)
      except Exception:  # pragma: nocover
        presentation.step_text = 'could not get GS path, exiting'
        return
      upload_uri = 'gs://{}/{}/{}'.format(gs_bucket, gs_path, filename)
      self._upload(file_path, upload_uri)
      presentation.links['gs_link'] = self.m.urls.get_gs_path_url(upload_uri)

  @exponential_retry(retries=3, condition=lambda e: getattr(e, 'had_timeout', False))
  def _upload(self, source, dest):
    self.m.gsutil(['cp', source, dest], timeout=10 * 60)

  def _get_duration(self, end_secs, start_secs):
    duration = datetime.timedelta(seconds=(end_secs - start_secs))
    return str(duration)

  def _get_unittest_step(self, build_steps):
    if self._test_data.enabled:
      return step_pb2.Step(
          status=common_pb2.SUCCESS,
          start_time=timestamp_pb2.Timestamp(seconds=1586287057),
          end_time=timestamp_pb2.Timestamp(seconds=1586280057))
    else:  # pragma: nocover
      for step in build_steps:
        if step.name == 'run ebuild tests':
          return step

      return None

  def add_stage_results(self):
    """Add stage results for DebugSymbols and Unittest stages."""
    self._metadata['results'] = [{
        'status': 'pass',
        'description': '',
        'name': 'DebugSymbols',
        'duration': '00:00:00',
        'summary': 'stage was successful',
        'log': '',
        'board': '',
    }]

    build = self._safe_buildbucket_get_self()
    unittest_step = self._get_unittest_step(build.steps)
    if unittest_step:
      success = unittest_step.status == common_pb2.SUCCESS
      self._metadata['results'].append({
          'status': 'pass' if success else 'fail',
          'description': '',
          'name': 'UnitTest',
          'duration': self._get_duration(unittest_step.end_time.seconds,
                                         unittest_step.start_time.seconds),
          'summary': ('stage was successful' if success else 'stage failed'),
          'log': '',
          'board': '',
      })

  def finalize_build(self, config, target, success):
    """Finish the build stats and upload metadata.json.

    Args:
      config(BuilderConfig): builder config of this builder.
      target (BuildTarget): The build target of this builder.
      success(bool): Did this build pass.
    """
    current_secs = int(self.m.time.time())
    self._metadata['status'] = {
        'status': 'pass' if success else 'fail',
        'create-time': self._print_time(current_secs),
        'summary': '',
    }

    build = self._safe_buildbucket_get_self()
    self._metadata['time'].update({
        'finish': self._print_time(current_secs),
        'duration': self._get_duration(current_secs, build.start_time.seconds),
    })
    self.upload_to_gs(config, target, partial=False)

  @contextlib.contextmanager
  def context(self, config, target):
    """Returns a context that upload final metadata.json to GS.

    Args:
      config(BuilderConfig): builder config of this builder.
      target (BuildTarget): The build target of this builder.
    """
    try:
      with self.m.step.nest('metadata setup'):
        self.add_default_entries()

      yield

      with self.m.step.nest('finalize metadata'):
        if self.m.cros_artifacts.has_output_artifacts(
            config.artifacts.artifacts_info):
          self.add_stage_results()
          self.finalize_build(config, target, success=True)
    except self.m.step.StepFailure:
      with self.m.step.nest('finalize metadata'):
        if self.m.cros_artifacts.has_output_artifacts(
            config.artifacts.artifacts_info):
          self.add_stage_results()
          self.finalize_build(config, target, success=False)

      raise
