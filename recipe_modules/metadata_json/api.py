# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API to write metadata json file into GS for GoldenEye consumption."""

import contextlib
import datetime
import email.utils
import time

from google.protobuf import timestamp_pb2

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import step as step_pb2

from RECIPE_MODULES.recipe_engine.time.api import exponential_retry
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure


class MetadataJsonApi(RecipeApi):
  """A module to write metadata.json into GS for GoldenEye consumption."""

  def __init__(self, properties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._metadata = {}
    self._add_defunct_entries()
    self._properties = properties

  def _add_defunct_entries(self):
    """These fields are no longer available."""
    self._metadata['build-number'] = 0
    self._metadata['build_id'] = 0
    self._metadata['board-metadata'] = {}
    # TODO(crbug/1148834): change this to 'parent_buildbucket_id'?
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

  def _safe_buildbucket_get_self(self, initial=False):
    if self.m.led.run_id:
      # If this is a led job, do not use the build_id of the cloned builder.
      # 8784717183252430977 is for an amd64-generic-cq run from 2023-04-04.
      build_id = self.test_api.led_build_id
    elif initial:
      # If this is the initial call, and start_time is non-zero, use bb.build.
      return (self.m.buildbucket.build
              if self.m.buildbucket.build.start_time.seconds else
              self.m.buildbucket.get(self.m.buildbucket.build.id))
    else:
      # Otherwise, we need to call buildbucket.get to have current information.
      build_id = self.m.buildbucket.build.id

    return self.m.buildbucket.get(build_id)

  def add_default_entries(self):
    """These fields are available at the start of the build."""
    build = self._safe_buildbucket_get_self(initial=True)
    if self._test_data.enabled:
      # If we are testing, and the caller didn't setup buildbucket to do a
      # simulated get, use buildbucket.build for the test, since everything
      # other than possibly start_time is correct in that record.
      build = (
          build
          if build.builder.builder == self.m.buildbucket.build.builder.builder
          else self.m.buildbucket.build)
    self._metadata['buildbucket_id'] = build.id
    builder_name = build.builder.builder
    self._metadata['builder-name'] = builder_name
    self._metadata['bot-config'] = builder_name
    # For now consider builder_type = bucket.
    self._metadata['builder_type'] = build.builder.bucket
    self._metadata['branch'] = self.m.cros_source.manifest_push

    self._metadata['time'] = {
        'start':
            self._print_time(build.start_time.seconds,
                             test_data='some start time')
    }

    config = self.m.cros_infra_config.config
    self._metadata['unibuild'] = config.general.unibuild
    dimensions = self.m.buildbucket.swarming_bot_dimensions_from_build(build)
    if dimensions:
      for dimension in dimensions:  # pragma: nocover
        if dimension.key == 'id':
          self._metadata['bot-hostname'] = dimension.value

  def add_version_entries(self, version_dict):
    """Update metadata with version info.

    Args:
      version_dict (dict): Map containing version info.
    """
    self._metadata['version'] = {
        'chrome': version_dict.get('chromeVersion', ''),
        'full': version_dict.get('fullVersion', ''),
        'milestone': version_dict.get('milestoneVersion', ''),
        'platform': version_dict.get('platformVersion', ''),
    }

  def add_entries(self, **kwargs):
    """Add elements to metadata.

    Args:
      kwargs (dict): dictionary of key-values to update.
    """
    self._metadata.update(kwargs)

  def get_metadata(self):
    """Get the metadata dict. Should only be used for unittesting.

    Returns: dict, metadata info.
    """
    return self._metadata

  def write_to_file(self, filename):
    """Write metadata dict to a tempfile.

    Args:
      filename (str): Filename to write to.

    Returns:
      str, path to the file written.
    """
    temp_dir = self.m.path.mkdtemp(prefix='metadata')
    file_path = temp_dir / filename
    self.m.file.write_json('writing ' + filename, file_path, self._metadata,
                           indent=4)
    return str(file_path)

  def upload_to_gs(self, config, targets, partial=False):
    """Upload metadata to GS at its current state.

    Args:
      config (BuilderConfig): builder config of this builder.
      targets (list[BuildTarget]): The build targets of this builder.
          The first element should be the build_target for the build, the entire
          list is used for additional publication locations.
      partial (bool): whether the metadata is incomplete.
    """
    with self.m.step.nest('upload metadata') as presentation:
      # Update the branch to what is actually being used.
      self.add_entries(branch=self.m.cros_source.manifest_push)
      filename = 'partial-metadata.json' if partial else 'metadata.json'
      file_path = self.write_to_file(filename)
      gs_bucket = config.artifacts.artifacts_gs_bucket
      try:
        gs_path = self.m.cros_artifacts.artifacts_gs_path(
            config.id.name, targets[0], config.id.type,
            template=self.m.cros_artifacts.gs_upload_path)
      except Exception as ex:  # pragma: nocover # pylint: disable=broad-except
        presentation.step_text = 'could not get GS path: {}'.format(ex)
        return
      upload_uri = 'gs://{}/{}/{}'.format(gs_bucket, gs_path, filename)
      self._upload(file_path, upload_uri)
      presentation.links['gs_link'] = self.m.urls.get_gs_path_url(upload_uri)
      for target in targets:
        for location in self._properties.additional_publish_locations:
          upload_location = self.m.cros_artifacts.artifacts_gs_path(
              config.id.name, target, config.id.type,
              template='gs://{}/{}'.format(location.gs_location, filename))
          self._upload(file_path, upload_location)

  @exponential_retry(retries=2, delay=datetime.timedelta(seconds=1),
                     condition=lambda e: getattr(e, 'had_timeout', False))
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
    for step in build_steps:  # pragma: nocover
      if step.name == 'run ebuild tests':
        return step
    return None  # pragma: nocover

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
      duration = self._get_duration(unittest_step.end_time.seconds,
                                    unittest_step.start_time.seconds)
      self._metadata['results'].append({
          'status': 'pass' if success else 'fail',
          'description': '',
          'name': 'UnitTest',
          'duration': duration,
          'summary': 'stage was successful' if success else 'stage failed',
          'log': '',
          'board': '',
      })

  def finalize_build(self, config, targets, success):
    """Finish the build stats and upload metadata.json.

    Args:
      config (BuilderConfig): builder config of this builder.
      targets (list[BuildTarget]): The build target of this builder.
      success (bool): Did this build pass.
    """
    if targets and targets[0] and targets[0].name:
      now = int(self.m.time.time())
      self._metadata['status'] = {
          'status': 'pass' if success else 'fail',
          'current-time': self._print_time(now),
          'summary': '',
      }

      build = self._safe_buildbucket_get_self()
      self._metadata['time'].update({
          'finish': self._print_time(now),
          'duration': self._get_duration(now, build.start_time.seconds),
      })
      self.upload_to_gs(config, targets, partial=False)

  @contextlib.contextmanager
  def context(self, config, targets=()):
    """Returns a context that upload final metadata.json to GS.

    Args:
      config (BuilderConfig): builder config of this builder.
      targets (list[BuildTarget]): The build targets of this builder.
    """
    try:
      boards = [x.name for x in targets]
      with self.m.step.nest('metadata setup'):
        self.add_default_entries()
        self.add_entries(boards=boards)

      yield

      with self.m.step.nest('finalize metadata'):
        if self.m.cros_artifacts.has_output_artifacts(
            config.artifacts.artifacts_info):
          self.add_stage_results()
          self.finalize_build(config, targets, success=True)
    except StepFailure:
      with self.m.step.nest('finalize metadata'):
        if self.m.cros_artifacts.has_output_artifacts(
            config.artifacts.artifacts_info):
          self.add_stage_results()
          self.finalize_build(config, targets, success=False)

      raise
