# -*- coding: utf-8 -*-

# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api

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

  def _print_time(self, time_secs):
    return '{} ({})'.format(
        email.utils.formatdate(timeval=time_secs, localtime=True),
        time.strftime('%Z', time.localtime(time_secs)))

  def add_default_entries(self):
    """These fields are available at the start of the build."""
    build = self.m.buildbucket.build
    self._metadata['buildbucket_id'] = build.id
    self._metadata['builder-name'] = build.builder.builder
    self._metadata['bot-config'] = build.builder.builder
    # For now consider builder_type = bucket.
    self._metadata['builder_type'] = build.builder.bucket
    # Branch is always master for now.
    self._metadata['branch'] = 'master'

    self._metadata['time'] = {
        'start': self._print_time(build.start_time.seconds)
    }

    build_target = self.m.cros_history.get_build_target(build)
    self._metadata['boards'] = [build_target]

    for dimension in build.infra.swarming.bot_dimensions:  # pragma: nocover
      if dimension.key == 'id':
        self._metadata['bot-hostname'] = dimension.value

  def add_version_entries(self, version_dict):
    """Update metadata with version info.

    Args:
      version_dict(dict): Map containing version info.
    """
    self._metadata['version'] = {
        'chrome': version_dict['chromeVersion'],
        'full': version_dict['fullVersion'],
        'platform': version_dict['platformVersion'],
        'milestone': version_dict['milestoneVersion'],
    }

  def get_metadata(self):
    """Get the metadata dict. Should only be used for unittesting.

    Returns: dict, metadata info.
    """
    return self._metadata
